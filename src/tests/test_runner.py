import argparse
import contextlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
import unittest.mock

import build_pages
import grade
import run_models as runner


class Fixture:
    def __init__(self, backend='lmstudio', behavior='normal', loaded_context=None):
        self.backend=backend;self.behavior=behavior;self.calls=[];self.loaded_context=loaded_context

    def __enter__(self):
        fixture=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def send_json(self,data,status=200):
                body=json.dumps(data).encode();self.send_response(status)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            def do_GET(self):
                fixture.calls.append(('GET',self.path,None))
                if self.path=='/api/v1/models' and fixture.backend=='lmstudio':
                    instances=[] if fixture.loaded_context is None else [{'id':'fixture-running','config':{'context_length':fixture.loaded_context}}]
                    return self.send_json({'models':[{'key':'fixture/model','type':'llm','display_name':'Fixture','loaded_instances':instances},
                                                     {'key':'embedding','type':'embedding'}]})
                if self.path=='/v1/models':
                    return self.send_json({'data':[{'id':'fixture/model','owned_by':'unsloth-studio' if fixture.backend=='unsloth' else 'test','loaded':False},
                                                  {'id':'ggml-vocab-test'}]})
                self.send_json({},404)
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fixture.calls.append(('POST',self.path,body))
                if self.path=='/api/v1/models/load':
                    return self.send_json({'status':'loaded','instance_id':'fixture-instance'})
                if self.path=='/api/inference/load':
                    return self.send_json({'status':'success','model':'fixture/model'})
                if self.path!='/v1/chat/completions':return self.send_json({},404)
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                prompt=body['messages'][0]['content'];qid='Q01' if '## Q01.' in prompt else 'Q02'
                key=grade.load_suite()[1]
                answer=json.dumps({'id':qid,'answer':key[qid]}) if fixture.behavior!='bad_json' else 'Not JSON'
                chunks=[{'choices':[{'index':0,'delta':{'reasoning_content':'Reasoning retained separately.'}}]},
                        {'choices':[{'index':0,'delta':{'content':answer}}]},
                        {'choices':[{'index':0,'delta':{},'finish_reason':'length' if fixture.behavior=='truncated' else 'stop'}]},
                        {'choices':[],'usage':{'prompt_tokens':20,'completion_tokens':10}}]
                for chunk in chunks:
                    self.wfile.write(('data: '+json.dumps(chunk)+'\n\n').encode())
                if fixture.behavior!='broken':self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        return self

    def __exit__(self,*_):
        self.server.shutdown();self.server.server_close();self.thread.join()


def args(folder,only='Q01,Q02',**kw):
    values=dict(chat_options=None,load_options=None,temperature=0,max_tokens=8192,timeout=10,
                context=32768,out=Path(folder),only=only,resume=False,load_timeout=10)
    values.update(kw)
    return argparse.Namespace(**values)


class RunnerTests(unittest.TestCase):
    def test_lmstudio_discover_load_sequential_and_resume(self):
        with Fixture() as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url+'/v1',key='not-a-real-key')
            self.assertEqual(server.models(),[{'id':'fixture/model','label':'Fixture','loaded':False}])
            runner.execute(args(folder),server,'fixture/model')
            posts=[(p,b) for verb,p,b in fake.calls if verb=='POST']
            self.assertEqual([p for p,b in posts],['/api/v1/models/load','/v1/chat/completions','/v1/chat/completions'])
            self.assertEqual(posts[0][1]['context_length'],32768)
            for i,(_,body) in enumerate(posts[1:],1):
                self.assertEqual(len(body['messages']),1)
                self.assertEqual(body['model'],'fixture-instance')
                self.assertEqual(body['messages'][0]['content'],(runner.REPO/'questions'/f'Q{i:02}.txt').read_text())
                self.assertNotIn('tools',body)
            output=Path(folder)
            result=json.loads((output/'raw'/'Q01.json').read_text())
            self.assertEqual(result['status'],'complete')
            self.assertEqual(result['reasoning'],'Reasoning retained separately.')
            self.assertEqual(result['usage']['completion_tokens'],10)
            self.assertEqual(json.loads((output/'results.json').read_text())['points'],4)
            self.assertNotIn('not-a-real-key',(output/'raw'/'run.json').read_text())
            before=len(fake.calls)
            runner.execute(args(folder,resume=True),server,'fixture/model')
            self.assertEqual(len(fake.calls),before)
            with self.assertRaisesRegex(ValueError,'configuration changed'):
                runner.execute(args(folder,resume=True,max_tokens=99),server,'fixture/model')

    def test_auto_pick_tests_the_loaded_instance_without_loading(self):
        with Fixture(loaded_context=65536) as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url)
            chosen=runner.pick_model(server.models())
            self.assertEqual(chosen,{'id':'fixture/model','label':'Fixture','loaded':True,'instance':'fixture-running','context':65536})
            runner.execute(args(folder,only='Q01'),server,chosen['id'],chosen)
            posts=[(p,b) for verb,p,b in fake.calls if verb=='POST']
            self.assertEqual([p for p,_ in posts],['/v1/chat/completions'])
            self.assertEqual(posts[0][1]['model'],'fixture-running')
            identity=json.loads((Path(folder)/'raw'/'run.json').read_text())['identity']
            self.assertEqual((identity['context'],identity['reused_loaded_model']),(65536,True))
            self.assertEqual(json.loads((Path(folder)/'results.json').read_text())['points'],2)

    def test_loaded_context_too_small_is_refused_before_any_request(self):
        with Fixture(loaded_context=4096) as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url)
            chosen=runner.pick_model(server.models())
            with self.assertRaisesRegex(ValueError,'4096 tokens of context'):
                runner.execute(args(folder,only='Q01'),server,chosen['id'],chosen)
            self.assertFalse(any(verb=='POST' for verb,_,_ in fake.calls))

    def test_pick_model_asks_only_when_ambiguous(self):
        a=dict(id='a',label='A',loaded=False);d=dict(id='d',label='D',loaded=False)
        b=dict(id='b',label='B',loaded=True,context=32768);c=dict(id='c',label='C',loaded=True)
        self.assertIs(runner.pick_model([a,b]),b)  # one loaded: no question
        self.assertIs(runner.pick_model([a]),a)  # only one listed: no question
        answers=iter(['2','1']);asked=[]
        def answer(prompt):asked.append(prompt);return next(answers)
        with unittest.mock.patch('builtins.input',answer):
            with contextlib.redirect_stdout(io.StringIO()) as shown:
                self.assertIs(runner.pick_model([a,b,c]),c)  # several loaded: only those are offered
            self.assertEqual(shown.getvalue().splitlines(),
                ['The server has 2 models loaded.','1. B [loaded, context 32768]','2. C [server reports loaded]'])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIs(runner.pick_model([a,d]),a)  # none loaded: all are offered
        self.assertEqual(len(asked),2)
        with self.assertRaises(ValueError):runner.pick_model([])

    def test_interactive_pick_lists_everything_with_loaded_preselected(self):
        a=dict(id='a',label='A',loaded=False);b=dict(id='b',label='B',loaded=True,context=65536)
        with unittest.mock.patch('builtins.input',lambda prompt:''),contextlib.redirect_stdout(io.StringIO()) as shown:
            self.assertIs(runner.pick_model([a,b],interactive=True),b)  # Enter accepts the loaded model
        self.assertEqual(shown.getvalue().splitlines(),['1. A','2. B [loaded, context 65536]'])
        with unittest.mock.patch('builtins.input',lambda prompt:'1'),contextlib.redirect_stdout(io.StringIO()):
            self.assertIs(runner.pick_model([a,b],interactive=True),a)
        answers=iter(['','2'])  # no default when nothing is loaded: Enter is refused
        with unittest.mock.patch('builtins.input',lambda prompt:next(answers)),contextlib.redirect_stdout(io.StringIO()):
            self.assertIs(runner.pick_model([a,dict(a,id='c',label='C')],interactive=True)['id'],'c')

    def test_run_folders_are_named_after_the_model_and_resume_finds_the_latest(self):
        with tempfile.TemporaryDirectory() as base:
            base=Path(base)
            first=runner.run_folder('Qwen3.8-Flash-Next-GGUF/Q8_0',base=base)
            self.assertRegex(first.name,r'^Qwen3\.8-Flash-Next-GGUF-Q8_0_\d{4}-\d{2}-\d{2}_\d{6}$')
            with self.assertRaisesRegex(ValueError,'No earlier run'):runner.run_folder('m',resume=True,base=base)
            for name in ('m_2026-01-01_000000','m_2026-02-01_000000','m_2026-03-01_000000'):
                (base/name/'raw').mkdir(parents=True)
            for name in ('m_2026-01-01_000000','m_2026-02-01_000000'):
                (base/name/'raw'/'run.json').write_text('{}')
            self.assertEqual(runner.run_folder('m',resume=True,base=base).name,'m_2026-02-01_000000')

    def test_chat_model_list_drops_embeddings_and_split_parts(self):
        class Fake(runner.Server):
            def json(self,path,payload=None,timeout=20):
                if path=='/api/v1/models':raise runner.ApiError('none',404)
                return {'data':[{'id':i,'owned_by':'unsloth-studio'} for i in
                        ('kimi/UD-Q2_K_XL','_loose:nomic-embed-text-v1.5.Q4_K_M','big/Model-00001-of-00003','big/Model-00002-of-00003')]}
        self.assertEqual([m['id'] for m in Fake('http://host').models()],['kimi/UD-Q2_K_XL','big/Model-00001-of-00003'])

    def test_unsloth_running_model_listed_once_and_served_by_its_short_name(self):
        class Fake(runner.Server):
            def json(self,path,payload=None,timeout=20):
                if path=='/api/v1/models':raise runner.ApiError('none',404)
                return {'data':[{'id':'Q8_0','owned_by':'unsloth-studio','loaded':True,'context_length':32768},
                                {'id':'Qwen3.8-Flash-Next-GGUF/Q8_0','owned_by':'unsloth-studio','loaded':True,'display_name':'Q8_0'},
                                {'id':'kimi-k2.5/UD-Q2_K_XL','owned_by':'unsloth-studio','loaded':False}]}
        models=Fake('http://host').models()
        self.assertEqual(models,[{'id':'Qwen3.8-Flash-Next-GGUF/Q8_0','label':'Qwen3.8-Flash-Next-GGUF/Q8_0','loaded':True,
                                  'instance':'Q8_0','context':32768},
                                 {'id':'kimi-k2.5/UD-Q2_K_XL','label':'kimi-k2.5/UD-Q2_K_XL','loaded':False}])
        self.assertIs(runner.pick_model(models),models[0])

    def test_finish_adds_a_local_leaderboard_entry(self):
        with Fixture() as fake,tempfile.TemporaryDirectory() as base,contextlib.redirect_stdout(io.StringIO()) as shown:
            base=Path(base);folder=base/'fixture-model_2026-11-05_120000'
            server=runner.Server(fake.url);server.models()
            runner.execute(args(folder,only='Q01'),server,'fixture/model')
            with unittest.mock.patch.object(runner,'RESULTS',base):
                runner.finish(folder,'fixture/model','temp 0 · max 8192 tokens')
            board=json.loads((base/'leaderboard.json').read_text())
            self.assertEqual([(e['id'],e['points'],e['answered']) for e in board],[(folder.name,2,1)])
            self.assertEqual(board[0]['link'],folder.name+'/report.html')
            self.assertTrue((folder/'report.html').exists() and (base/'leaderboard.html').exists())
            self.assertIn('issues/new?template=model-test.yml',shown.getvalue())

    def test_unsloth_native_load(self):
        with Fixture('unsloth') as fake:
            server=runner.Server(fake.url);models=server.models()
            self.assertEqual(server.backend,'unsloth')
            self.assertEqual([m['id'] for m in models],['fixture/model'])
            inference_model,_=server.load('fixture/model',32768,{'n_parallel':1},10)
            self.assertEqual(inference_model,'fixture/model')
            self.assertEqual([c for c in fake.calls if c[0]=='POST'][-1],
                             ('POST','/api/inference/load',{'model_path':'fixture/model','max_seq_length':32768,'n_parallel':1}))
            # Then it asks which model the server now serves, to name it correctly in chat.
            self.assertEqual(fake.calls[-1],('GET','/v1/models',None))

    def test_unsloth_chat_uses_the_id_the_server_now_serves(self):
        # Real case: the inventory entry "short-name" loads as hub ID "unsloth/short-name",
        # and chat answers 404 "model not loaded" to the short name.
        class Fake(runner.Server):
            def __init__(self,rows):
                super().__init__('http://127.0.0.1:9',backend='unsloth');self.rows=rows
            def json(self,path,payload=None,timeout=20):
                if path=='/api/inference/load':return {'status':'success','model':'/private/dir/model.gguf'}
                raise AssertionError(path)
            def models(self):
                if self.rows is None:raise runner.ApiError('down')
                return self.rows
        hub={'id':'unsloth/short-name','label':'unsloth/short-name','loaded':True,'context':32768}
        idle={'id':'short-name','label':'short-name','loaded':False}
        twin={'id':'short-name','label':'short-name','loaded':True,'instance':'unsloth/short-name','context':32768}
        def load(rows):return Fake(rows).load('short-name',32768,{},10)[0]
        self.assertEqual(load([idle,hub]),'unsloth/short-name')
        self.assertEqual(load([twin]),'unsloth/short-name')
        # Never the private path from the load response; unclear or failed lookups keep the selection.
        self.assertEqual(load([idle]),'short-name')
        self.assertEqual(load([hub,dict(hub,id='other')]),'short-name')
        self.assertEqual(load(None),'short-name')

    def test_generic_server_no_fake_load_endpoint(self):
        with Fixture('generic') as fake:
            server=runner.Server(fake.url);server.models()
            self.assertEqual(server.backend,'openai')
            _,load=server.load('fixture/model',32768,{},10)
            self.assertEqual(load['status'],'server_managed')
            self.assertFalse(any(verb=='POST' for verb,_,_ in fake.calls))

    def test_load_identity_cannot_be_overridden(self):
        with self.assertRaises(ValueError):runner.Server('http://localhost',backend='unsloth').load('m',32,{'model_path':'other'},1)

    def test_invalid_url_credentials_rejected(self):
        for url in ['file:///tmp/key','http://user:pass@host','http://host/?key=secret','http://host/#secret']:
            with self.assertRaises(ValueError):runner.Server(url)

    def test_malformed_output_is_zero_credit_with_raw_evidence(self):
        with Fixture(behavior='bad_json') as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url);server.models()
            runner.execute(args(folder,only='Q01'),server,'fixture/model')
            output=Path(folder)
            record=json.loads((output/'answers.jsonl').read_text())
            self.assertEqual(record['answer'],{'assignments':None,'count':None})
            self.assertIn('RECORDER ZERO-CREDIT',record['rationale'])
            self.assertEqual((output/'raw'/'Q01.answer.txt').read_text(),'Not JSON')
            result=json.loads((output/'results.json').read_text())
            self.assertEqual((result['points'],result['answered']),(0,1))

    def test_truncation_recorded_zero_credit_and_retry_archived(self):
        with Fixture(behavior='truncated') as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url);server.models()
            runner.execute(args(folder,only='Q01'),server,'fixture/model')
            output=Path(folder)
            self.assertEqual(json.loads((output/'raw'/'Q01.json').read_text())['status'],'truncated')
            self.assertEqual(json.loads((output/'results.json').read_text())['points'],0)
            fake.behavior='normal'
            runner.execute(args(folder,only='Q01',resume=True),server,'fixture/model')
            self.assertEqual(json.loads((output/'results.json').read_text())['points'],2)
            self.assertEqual(len(list((output/'raw'/'attempts').glob('Q01-*'))),1)

    def test_broken_stream_stops_before_next_question(self):
        with Fixture(behavior='broken') as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url);server.models()
            with self.assertRaises(runner.ApiError):runner.execute(args(folder),server,'fixture/model')
            self.assertEqual(len([1 for v,p,b in fake.calls if p=='/v1/chat/completions']),1)
            self.assertFalse((Path(folder)/'raw'/'Q02.json').exists())
            self.assertEqual(json.loads((Path(folder)/'raw'/'Q01.json').read_text())['status'],'incomplete')

    def test_sse_multiline_event(self):
        data=io.BytesIO(b': heartbeat\n\ndata: {"a":\ndata: 1}\n\ndata: [DONE]\n\n')
        events=list(runner.sse_events(data))
        self.assertEqual(json.loads(events[0]),{'a':1})
        self.assertEqual(events[1],'[DONE]')

    def test_run_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory(dir=runner.ROOT) as folder:
            with runner.run_lock(Path(folder)):
                with self.assertRaisesRegex(ValueError,'Another runner'):
                    with runner.run_lock(Path(folder)):pass

    def test_demo_pages_build_publishes_only_example(self):
        with tempfile.TemporaryDirectory(dir=runner.ROOT) as folder:
            build_pages.build(folder)
            self.assertEqual({p.name for p in Path(folder).iterdir()},{'index.html','chart.svg','.nojekyll'})
            page=(Path(folder)/'index.html').read_text()
            self.assertIn('How does your model score?',page)
            self.assertIn('not a measured model result',page)
            self.assertIn('https://github.com/Prism77Proton/LocalLLMTest/issues/new',page)
            self.assertNotIn('<script',page)


if __name__=='__main__':unittest.main()
