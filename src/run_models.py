#!/usr/bin/env python3
"""Pick a model from a server, ask it one fresh question at a time, then grade and report.

Run with no arguments for the interactive flow. Each run gets its own folder under
results/, named after the model, with report.html and the raw recordings, and an
entry in the local leaderboard (results/leaderboard.html).
"""
import argparse
import contextlib
import datetime
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import grade
import leaderboard
import submit

ROOT = Path(__file__).resolve().parent  # src/: the engine and its data
REPO = ROOT.parent  # what users see: questions/, results/, README
RESULTS = REPO / 'results'
MAX_RESPONSE = 16 * 1024 * 1024
# Room left for a question prompt beside --max-tokens in an already-loaded model.
PROMPT_RESERVE = 2048


class ApiError(RuntimeError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ApiError('Redirect refused; enter the final server URL directly.', code)


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def lmstudio_model(m):
    entry=dict(id=m['key'],label=m.get('display_name') or m['key'],loaded=bool(m.get('loaded_instances')))
    instances=[i for i in m.get('loaded_instances') or [] if isinstance(i,dict) and isinstance(i.get('id'),str)]
    if instances:
        # Requests go to the running instance, which keeps the context it was loaded with.
        entry['instance']=instances[0]['id']
        context=(instances[0].get('config') or {}).get('context_length')
        if isinstance(context,int) and not isinstance(context,bool):
            entry['context']=context
    return entry


class Server:
    def __init__(self, url, key='', backend='auto'):
        parts = urllib.parse.urlsplit(url.strip().rstrip('/'))
        if parts.scheme not in ('http', 'https') or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('Use an http(s) server URL without credentials, query or fragment.')
        path = parts.path.rstrip('/')
        if path.endswith('/v1'):
            path = path[:-3]
        self.root = urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, '', ''))
        self.key = key
        self.backend = backend
        # Direct local connections; never send a LAN credential via an environment proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def open(self, path, payload=None, timeout=20):
        headers = {'Accept': 'application/json'}
        if self.key:
            headers['Authorization'] = 'Bearer ' + self.key
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.root+path, data=data, headers=headers)
        try:
            return self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            # Don't echo server responses: they can contain private headers/paths.
            status=error.code
            error.close()
            raise ApiError(f'HTTP {status} from {path}. Check authentication and server compatibility.', status) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ApiError(f'Connection failed or timed out at {path}.') from None

    def json(self, path, payload=None, timeout=20):
        with self.open(path, payload, timeout) as response:
            data = response.read(MAX_RESPONSE+1)
        if len(data) > MAX_RESPONSE:
            raise ApiError('Server JSON response exceeds 16 MiB.')
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise ApiError(f'Expected a JSON response from {path}.') from None

    def models(self):
        if self.backend in ('auto', 'lmstudio'):
            try:
                data = self.json('/api/v1/models')
                if isinstance(data.get('models'), list):
                    self.backend = 'lmstudio'
                    return [lmstudio_model(m) for m in data['models'] if m.get('type')=='llm']
                if self.backend=='lmstudio':
                    raise ApiError('Unexpected LM Studio model-list response.')
            except ApiError as error:
                if self.backend=='lmstudio' or error.status not in (404,405):
                    raise
        data = self.json('/v1/models')
        rows = data.get('data')
        if not isinstance(rows,list):
            raise ApiError('Expected a data array from /v1/models.')
        if self.backend=='auto':
            self.backend = 'unsloth' if any(m.get('owned_by')=='unsloth-studio' for m in rows) else 'openai'
        models=[]
        for m in rows:
            model_id=m.get('id')
            if not isinstance(model_id,str) or m.get('is_embedding') or 'ggml-vocab-' in model_id:
                continue
            # Not chat models: embedding models, and the 2nd+ parts of a split GGUF.
            if 'embed' in model_id.lower() or re.search(r'-(?!00001)\d{5}-of-\d{5}$',model_id):
                continue
            entry=dict(id=model_id,label=model_id,loaded=m.get('loaded') is True)
            context=m.get('context_length')
            if entry['loaded'] and isinstance(context,int) and not isinstance(context,bool):
                entry['context']=context
            models.append(entry)
        # Unsloth lists the running model twice: under a short serving name that carries
        # its context, and as the inventory entry whose display name is that short name.
        # Show the inventory name once; send requests to the serving name.
        displays={m.get('id'):m.get('display_name') for m in rows if isinstance(m,dict)}
        for active in [m for m in models if m['loaded'] and 'context' in m]:
            twins=[m for m in models if m is not active and m['loaded'] and 'context' not in m
                   and (displays.get(m['id'])==active['id'] or m['id'].endswith('/'+active['id']))]
            if len(twins)==1:
                twins[0].update(instance=active['id'],context=active['context'])
                models.remove(active)
        return models

    def load(self, model, context, options, timeout):
        protected={'model','model_path','context_length','max_seq_length'}
        if protected.intersection(options):
            raise ValueError('Load options cannot override model identity or context; use CLI flags.')
        if self.backend=='lmstudio':
            body={'model':model,'context_length':context,'echo_load_config':True,**options}
            response=self.json('/api/v1/models/load',body,timeout)
            if response.get('status')!='loaded' or not response.get('instance_id'):
                raise ApiError('LM Studio did not confirm the model loaded.')
            return response['instance_id'], response
        if self.backend=='unsloth':
            body={'model_path':model,'max_seq_length':context,**options}
            response=self.json('/api/inference/load',body,timeout)
            if response.get('status') not in ('loaded','success','ready'):
                raise ApiError('Unsloth did not confirm the model loaded; check its load status/logs.')
            # Chat must use the public ID the server now serves, which can differ from the
            # inventory entry that was selected (a short or local name loads as its hub ID,
            # and the server then answers 404 to the old name). Read it from /v1/models;
            # the load response may carry a private path, so it is not used.
            try:
                running=[m for m in self.models() if m['loaded']]
            except ApiError:
                running=[]
            if len(running)==1:
                return running[0].get('instance',running[0]['id']), response
            return model, response
        if options:
            raise ValueError('An OpenAI-compatible endpoint has no standard load-options API.')
        return model, {'status':'server_managed','note':'No standard load API; the selected model must already be served or auto-loaded by this server.'}


def sse_events(response):
    lines=[]; size=0
    while True:
        raw=response.readline(1024*1024+1)
        if not raw:
            if lines:
                yield '\n'.join(lines)
            return
        if len(raw)>1024*1024:
            raise ApiError('SSE line exceeds 1 MiB.')
        line=raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if lines:
                yield '\n'.join(lines)
            lines=[];size=0
        elif line.startswith('data:'):
            value=line[5:].lstrip(' ')
            size+=len(raw)
            if size>MAX_RESPONSE:
                raise ApiError('SSE event exceeds 16 MiB.')
            lines.append(value)


def text_value(value):
    if value is None:
        return ''
    if isinstance(value,str):
        return value
    if isinstance(value,list) and all(isinstance(v,dict) and v.get('type')=='text' and isinstance(v.get('text'),str) for v in value):
        return ''.join(v['text'] for v in value)
    raise ApiError('Unsupported content/reasoning shape; raw events preserved.')


def one_question(server, model, prompt, qid, folder, settings):
    result=dict(id=qid,status='in_progress',started=stamp(),answer='',reasoning='',usage=None,
                finish_reason=None,first_token_seconds=None,elapsed_seconds=None)
    payload=dict(model=model, messages=[{'role':'user','content':prompt}], stream=True,
                 stream_options={'include_usage':True},temperature=settings['temperature'],
                 max_tokens=settings['max_tokens'],**settings['chat_options'])
    atomic_json(folder/f'{qid}.json',result)
    started=time.monotonic();done=False;total=0;response=None;timer=None;expired=threading.Event()
    def abort_response():
        expired.set()
        # Unblock a stalled HTTP read at the overall deadline on Linux and Windows.
        try:
            response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
        except (AttributeError,OSError):
            pass
    try:
        with (folder/f'{qid}.events.jsonl').open('w',encoding='utf-8',buffering=1) as log:
            response=server.open('/v1/chat/completions',payload,settings['timeout'])
            timer=threading.Timer(max(0.001,settings['timeout']-(time.monotonic()-started)),abort_response)
            timer.daemon=True;timer.start()
            with response:
                if 'text/event-stream' not in response.headers.get('Content-Type',''):
                    raise ApiError('Server did not return an SSE stream.')
                for data in sse_events(response):
                    if expired.is_set() or time.monotonic()-started>settings['timeout']:
                        raise TimeoutError('Question deadline exceeded.')
                    if data=='[DONE]':
                        done=True;break
                    event=json.loads(data)
                    total+=len(data.encode())
                    if total>MAX_RESPONSE:
                        raise ApiError('Question response exceeds 16 MiB.')
                    log.write(json.dumps({'elapsed_seconds':round(time.monotonic()-started,6),'event':event},ensure_ascii=False)+'\n')
                    if event.get('error'):
                        raise ApiError('Server returned an inference error; inspect the saved events locally.')
                    if event.get('usage') is not None:
                        result['usage']=event['usage']
                    if event.get('timings') is not None:
                        result['timings']=event['timings']
                    for choice in event.get('choices',[]):
                        if choice.get('index',0)!=0:
                            raise ApiError('Unexpected multiple completions.')
                        delta=choice.get('delta') or {}
                        if delta.get('tool_calls') or delta.get('function_call'):
                            raise ApiError('Unexpected tool call in closed-book test.')
                        content=text_value(delta.get('content'))
                        reasoning=text_value(delta.get('reasoning_content') or delta.get('reasoning'))
                        if (content or reasoning) and result['first_token_seconds'] is None:
                            result['first_token_seconds']=round(time.monotonic()-started,6)
                        result['answer']+=content;result['reasoning']+=reasoning
                        if choice.get('finish_reason'):
                            result['finish_reason']=choice['finish_reason']
            if expired.is_set():
                raise TimeoutError('Question deadline exceeded.')
            result['status']='complete' if done and result['finish_reason']=='stop' and result['answer'].strip() else 'incomplete'
            if result['finish_reason']=='length':
                result['status']='truncated'
    except KeyboardInterrupt:
        result['status']='interrupted'
        raise
    except Exception as error:
        result['status']='error'
        result['error']=str(error) if isinstance(error,(ApiError,TimeoutError)) else type(error).__name__
    finally:
        if timer:
            timer.cancel()
        if response:
            response.close()
        result['finished']=stamp()
        result['elapsed_seconds']=round(time.monotonic()-started,6)
        atomic_json(folder/f'{qid}.json',result)
        (folder/f'{qid}.answer.txt').write_text(result['answer'],encoding='utf-8')
        (folder/f'{qid}.reasoning.txt').write_text(result['reasoning'],encoding='utf-8')
    return result


def export_run(folder, model):
    """Grade what is recorded so far into folder; raw evidence stays in folder/raw.

    Completed format/truncation failures get two null fields (zero credit)."""
    raw=folder/'raw'
    suite=json.loads((ROOT/'suite.json').read_text())
    records=[];failures=[];performance=[]
    for q in suite['questions']:
        p=raw/f'{q["id"]}.json'
        if not p.exists():continue
        value=json.loads(p.read_text())
        performance.append({k:value.get(k) for k in ('id','status','elapsed_seconds','first_token_seconds','usage','finish_reason')})
        if value['status'] not in ('complete','truncated'):
            failures.append(dict(id=q['id'],status=value['status']));continue
        try:
            if value['status']=='truncated':raise grade.SubmissionError('Output token limit reached.')
            parsed=grade.parse_answers(value['answer'],suite)
            if list(parsed)!=[q['id']]:raise grade.SubmissionError('Response ID does not match the requested question.')
            records.append(json.dumps(parsed[q['id']],ensure_ascii=False))
        except grade.SubmissionError as error:
            failures.append(dict(id=q['id'],status='format_error',error=str(error)))
            # Fixed zero-credit outcome for a known requested question, never an
            # inferred/corrected answer. Raw response and hash remain auditable.
            records.append(json.dumps(dict(id=q['id'],answer={field:None for field in q['fields']},
                rationale='RECORDER ZERO-CREDIT FORMAT/TRUNCATION FAILURE: '+str(error)+
                ' Raw answer SHA-256: '+hashlib.sha256(value['answer'].encode()).hexdigest())))
    text='\n'.join(records)+('\n' if records else '')
    (folder/'answers.jsonl').write_text(text,encoding='utf-8')
    atomic_json(raw/'performance.json',performance)
    atomic_json(raw/'recording-status.json',dict(exported=len(records),excluded=failures,
        note='Known-question format/truncation failures export null fields (zero credit), never repaired answers. Transport failures are missing; resume them. Raw evidence is preserved.'))
    result=grade.evaluate(text,model)
    grade.write_reports(result,folder)
    return result


@contextlib.contextmanager
def run_lock(folder):
    """OS-released lock survives neither a crash nor a normal exit; Windows+Unix."""
    with (folder/'.runner.lock').open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise ValueError('Another runner is using this output folder.') from None
            try:yield
            finally:
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise ValueError('Another runner is using this output folder.') from None
            try:yield
            finally:fcntl.flock(handle,fcntl.LOCK_UN)


def choose(items, label, default=None):
    """Numbered pick; Enter accepts the default index when there is one."""
    if not items:raise ValueError(f'No {label} available.')
    for n,item in enumerate(items,1):
        print(f'{n}. {item}')
    hint=f' [{default+1}]' if default is not None else ''
    while True:
        value=input(f'Choose {label} number{hint}: ').strip()
        if not value and default is not None:return default
        if value.isdigit() and 1<=int(value)<=len(items):return int(value)-1
        print('Enter a listed number.')


def loaded_note(m):
    if not m['loaded']:return ''
    return f' [loaded, context {m["context"]}]' if 'context' in m else ' [server reports loaded]'


def pick_model(models, interactive=False):
    """Interactive: list every model, the loaded one pre-selected. Otherwise use the
    loaded model, asking only when that is ambiguous."""
    if not models:raise ValueError('No models available.')
    loaded=[m for m in models if m['loaded']]
    if interactive:
        default=models.index(loaded[0]) if len(loaded)==1 else 0 if len(models)==1 else None
        return models[choose([m['label']+loaded_note(m) for m in models],'model',default)]
    if len(loaded)==1:return loaded[0]
    if not loaded and len(models)==1:return models[0]
    if loaded:print(f'The server has {len(loaded)} models loaded.')
    candidates=loaded or models
    return candidates[choose([m['label']+loaded_note(m) for m in candidates],'model')]


def execute(args,server,model,loaded=None):
    """loaded: the server's entry for an already-loaded model, tested as it runs."""
    suite_raw=(ROOT/'suite.json').read_bytes()
    suite=json.loads(suite_raw)
    prompts={q['id']:(REPO/'questions'/f'{q["id"]}.txt').read_text(encoding='utf-8') for q in suite['questions']}
    chat_options=json.loads(args.chat_options.read_text()) if args.chat_options else {}
    load_options=json.loads(args.load_options.read_text()) if args.load_options else {}
    if not isinstance(chat_options,dict) or not isinstance(load_options,dict):raise ValueError('Options must be JSON objects.')
    if {'messages','model','stream','stream_options','tools','tool_choice','n','max_tokens','temperature'}.intersection(chat_options):
        raise ValueError('Chat options cannot override test isolation, transport or CLI settings.')
    settings=dict(temperature=args.temperature,max_tokens=args.max_tokens,timeout=args.timeout,chat_options=chat_options)
    identity=dict(server=server.root,backend=server.backend,selected_model=model,context=args.context,
        suite_sha256=hashlib.sha256(suite_raw).hexdigest(),
        prompt_sha256={qid:hashlib.sha256(text.encode()).hexdigest() for qid,text in prompts.items()},
        settings=settings,load_options=load_options)
    if loaded is not None:
        if load_options:raise ValueError('Load options only apply when the runner loads the model; pass --model to load it.')
        context=loaded.get('context')
        if context is not None and context<args.max_tokens+PROMPT_RESERVE:
            raise ValueError(f'The loaded model has {context} tokens of context, too small for --max-tokens '
                             f'{args.max_tokens} plus a question. Reload it with more context, or pass --model to load it at --context.')
        identity.update(context=context,reused_loaded_model=True)
    folder=args.out.resolve();raw=folder/'raw';raw.mkdir(parents=True,exist_ok=True)
    if (folder/'run.json').exists() and not (raw/'run.json').exists():
        raise ValueError('That folder was recorded by an older version of the runner; choose a new folder.')
    selected=args.only.split(',') if args.only else list(prompts)
    if any(qid not in prompts for qid in selected) or len(selected)!=len(set(selected)):
        raise ValueError('Use unique question IDs such as --only Q01,Q02.')
    # Canonical exam order, even when --only was supplied out of order.
    selected=[qid for qid in prompts if qid in selected]
    with run_lock(raw):
        manifest_path=raw/'run.json'
        if manifest_path.exists():
            manifest=json.loads(manifest_path.read_text())
            if manifest['identity']!=identity:raise ValueError('Resume configuration changed; choose a new output folder.')
            if not args.resume:raise ValueError('Run already exists. Use --resume or a new output folder.')
        else:
            if any(raw.glob('Q[0-9][0-9].json')):raise ValueError('Orphaned question records; choose a fresh folder.')
            manifest=dict(identity=identity,started=stamp())
            atomic_json(manifest_path,manifest)
        pending=[]
        for qid in selected:
            p=raw/f'{qid}.json'
            if p.exists():
                prior=json.loads(p.read_text())
                if prior.get('status')=='complete':continue
                # Preserve failed/interrupted evidence before replacing it on resume.
                archive=raw/'attempts'/f'{qid}-{time.time_ns()}'
                archive.mkdir(parents=True)
                for old in raw.glob(qid+'.*'):old.replace(archive/old.name)
            pending.append(qid)
        if not pending:
            export_run(folder,model);print('All selected questions already recorded; report refreshed.');return
        if loaded is not None:
            inference_model=loaded.get('instance',model)
            load_result=dict(status='already_loaded',instance_id=inference_model,context_length=loaded.get('context'))
            context=f' with {loaded["context"]} tokens of context' if 'context' in loaded else ''
            print(f'Using {model}, already loaded{context}, without reloading …',flush=True)
        else:
            print(f'Loading {model} through {server.backend} API …',flush=True)
            inference_model,load_result=server.load(model,args.context,load_options,args.load_timeout)
        # Server results may include paths and load settings; stay local under ignored results/.
        atomic_json(raw/'load-result.json',load_result)
        manifest['inference_model']=inference_model;atomic_json(manifest_path,manifest)
        try:
            for n,qid in enumerate(pending,1):
                print(f'{qid} ({n}/{len(pending)}): asking …',flush=True)
                result=one_question(server,inference_model,prompts[qid],qid,raw,settings)
                graded=export_run(folder,model)
                # Nothing is gradable until one answer is recorded.
                points=next((q['points'] for q in graded['questions'] if q['id']==qid),0)
                total=f'{graded["points"]}/{graded["maximum"]}' if graded['status']=='valid' else 'none yet'
                print(f'{qid}: {result["status"]}, {points}/2 points, {result["elapsed_seconds"]:.1f}s · '
                      f'running total {total}',flush=True)
                if result['status'] in ('error','incomplete','interrupted'):
                    raise ApiError('Stopped after a transport/incomplete-response error. Resume to retry that question.')
        finally:
            export_run(folder,model)


def slug(model):
    return re.sub(r'[^A-Za-z0-9._-]+','-',model).strip('-.')[:80] or 'model'


def run_folder(model, resume=False, base=RESULTS):
    """New runs get results/<model>_<date-time>; --resume picks that model's latest run."""
    if resume:
        runs=sorted(p for p in base.glob(slug(model)+'_*') if (p/'raw'/'run.json').exists())
        if not runs:raise ValueError(f'No earlier run of {model} under {base} to resume.')
        return runs[-1]
    return base/f'{slug(model)}_{datetime.datetime.now():%Y-%m-%d_%H%M%S}'


def finish(folder, model, settings_note, submit_mode=None):
    """Print the score, add the local leaderboard entry and offer to submit it.

    submit_mode: None asks (complete runs, at a terminal only), True submits without
    asking (complete runs only), False only shows how to share it by hand."""
    results=folder/'results.json'
    if not results.exists():return
    result=json.loads(results.read_text())
    if result.get('status')!='valid' or not result.get('answered'):return
    print(f'\nScore: {result["points"]}/{result["maximum"]} · {result["answered"]}/{len(result["questions"])} answered')
    for name,c in result['categories'].items():print(f'  {name}: {c["points"]}/{c["maximum"]}')
    leaderboard.record_local(folder,result,RESULTS)
    print(f'Report: {folder/"report.html"}')
    print(f'Local leaderboard: {RESULTS/"leaderboard.html"}')
    label=leaderboard.clean_name(f'{model} · {settings_note}')
    complete=result.get('complete') is True
    if submit_mode is True and not complete:
        print(f'Not submitted: only {result["answered"]}/{len(result["questions"])} answered. '
              'Resume with --resume, then run: llmtest submit')
    elif submit_mode is not False and complete and (submit_mode is True or sys.stdin.isatty()):
        submit.submit_run(folder,label,confirm=submit_mode is None)
        return
    print(f'Share it: open {submit.form_url(label)}')
    print(f'  and paste the contents of {folder/"answers.jsonl"} into Answers.')


def latest_run(base=None):
    base=RESULTS if base is None else base
    runs=list(base.glob('*/results.json'))
    if not runs:raise ValueError('No finished runs under results/.')
    return max(runs,key=lambda p:p.stat().st_mtime).parent


def run_label(folder, result):
    """The name finish() builds for a run, rebuilt from its manifest."""
    try:
        identity=json.loads((folder/'raw'/'run.json').read_text())['identity']
        settings=identity['settings']
        note=f'temp {settings["temperature"]:g} · max {settings["max_tokens"]} tokens'
        return leaderboard.clean_name(f'{identity["selected_model"]} · {note}')
    except (OSError,ValueError,KeyError,TypeError):
        return leaderboard.clean_name(result.get('model') or 'Unnamed model')


def submit_earlier(folder=None, confirm=True, base=None):
    """Submit a finished run's answers without running anything (llmtest submit)."""
    folder=(folder or latest_run(base)).resolve()
    try:result=json.loads((folder/'results.json').read_text())
    except (OSError,ValueError):raise ValueError(f'No finished run in {folder}.') from None
    if result.get('status')!='valid' or result.get('complete') is not True:
        raise ValueError(f'That run has {result.get("answered",0)}/50 answered; resume it '
                         '(llmtest --resume) before submitting.')
    print(f'Run: {folder}')
    return 0 if submit.submit_run(folder,run_label(folder,result),confirm=confirm) else 1


def ask_url(saved):
    last=saved.read_text().strip() if saved.exists() else ''
    hint=f' [{last}]' if last else ' (for example http://localhost:1234)'
    return input(f'Server URL{hint}: ').strip() or last


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',action='append',help='Repeat for a list of servers; root URL or /v1 accepted.')
    parser.add_argument('--backend',choices=['auto','unsloth','lmstudio','openai'],default='auto')
    parser.add_argument('--key-file',type=Path)
    parser.add_argument('--key-env',default='MODEL_API_KEY')
    parser.add_argument('--model',help='Exact inventory model ID, loaded at --context. Default: pick from the list '
                        '(the loaded model is pre-selected); without a terminal, the loaded model.')
    parser.add_argument('--list',action='store_true',help='Discovery only; never load or infer.')
    parser.add_argument('--out',type=Path,help='Run folder. Default: results/<model>_<date-time>.')
    parser.add_argument('--only',help='Comma-separated IDs; default all 50, sequentially.')
    parser.add_argument('--resume',action='store_true',help="Continue --out, or this model's latest run.")
    parser.add_argument('--context',type=int,default=32768)
    parser.add_argument('--max-tokens',type=int,default=8192)
    parser.add_argument('--temperature',type=float,default=0)
    parser.add_argument('--timeout',type=int,default=10800,help='Per-question timeout seconds.')
    parser.add_argument('--load-timeout',type=int,default=1800)
    parser.add_argument('--load-options',type=Path,help='Backend-specific JSON object, sent only at loading.')
    parser.add_argument('--chat-options',type=Path,help='Optional backend-specific generation settings (e.g. thinking).')
    parser.add_argument('--submit',action='store_true',help='When the run is complete, post it to the public '
                        'leaderboard without asking (needs a GitHub login; see README).')
    parser.add_argument('--no-submit',action='store_true',help='Do not offer to submit at the end.')
    parser.add_argument('--submit-only',action='store_true',help="Submit an earlier run's answers instead of "
                        'testing: --out FOLDER, default the latest run. Asks first unless --submit is given.')
    args=parser.parse_args()
    if min(args.context,args.max_tokens,args.timeout,args.load_timeout)<=0:parser.error('Sizes and timeouts must be positive.')
    if not math.isfinite(args.temperature) or args.temperature<0:parser.error('Temperature must be finite and nonnegative.')
    if args.submit and args.no_submit:parser.error('--submit and --no-submit contradict each other.')
    if args.submit_only:
        if args.no_submit:parser.error('--submit-only and --no-submit contradict each other.')
        return submit_earlier(args.out,confirm=not args.submit)
    submit_mode=True if args.submit else False if args.no_submit else None
    interactive=sys.stdin.isatty()
    saved=RESULTS/'.last-server'
    urls=args.url or [ask_url(saved)]
    url=urls[choose(urls,'server')] if len(urls)>1 else urls[0]
    if not url:raise ValueError('Enter the server URL, for example http://localhost:1234.')
    key=args.key_file.read_text().strip() if args.key_file else os.environ.get(args.key_env,'').strip()
    server=Server(url,key,args.backend)
    try:
        models=server.models()
    except ApiError as error:
        if error.status not in (401,403) or key or not os.isatty(0):raise
        server.key=getpass.getpass('Server API key (hidden): ').strip()
        models=server.models()
    print(f'Server: {server.root} · {server.backend}',flush=True)
    RESULTS.mkdir(exist_ok=True);saved.write_text(server.root+'\n')
    if args.list:
        for m in models:print(m['id']+loaded_note(m))
        return 0
    loaded=None
    if args.model:
        if args.model not in [m['id'] for m in models]:raise ValueError('Model ID not in server inventory; use --list.')
        model=args.model
    else:
        chosen=pick_model(models,interactive)
        model=chosen['id']
        loaded=chosen if chosen['loaded'] else None
        print(f'Model: {model}{loaded_note(chosen)}',flush=True)
    if server.backend=='openai' and loaded is None:
        print('This server has no supported management API. It must already serve/auto-load the selected model.',flush=True)
    args.out=args.out or run_folder(model,args.resume)
    print(f'Run folder: {args.out}',flush=True)
    try:
        execute(args,server,model,loaded)
    finally:
        finish(args.out.resolve(),model,f'temp {args.temperature:g} · max {args.max_tokens} tokens',submit_mode)
    return 0


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nRecording stopped; partial output saved. The server model may still be resident/running.')
        raise SystemExit(130)
    except (ApiError,ValueError,OSError) as error:
        print('Error:',error)
        raise SystemExit(1)
