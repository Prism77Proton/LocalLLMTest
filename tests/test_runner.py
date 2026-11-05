import argparse
import contextlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

import build_pages
import grade
import run_models as runner


class Fixture:
    def __init__(self, backend='lmstudio', behavior='normal'):
        self.backend=backend;self.behavior=behavior;self.calls=[]

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
                    return self.send_json({'models':[{'key':'fixture/model','type':'llm','display_name':'Fixture','loaded_instances':[]},
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
                self.assertEqual(body['messages'][0]['content'],(runner.ROOT/'questions'/f'Q{i:02}.txt').read_text())
                self.assertNotIn('tools',body)
            output=Path(folder)
            result=json.loads((output/'Q01.json').read_text())
            self.assertEqual(result['status'],'complete')
            self.assertEqual(result['reasoning'],'Reasoning retained separately.')
            self.assertEqual(result['usage']['completion_tokens'],10)
            self.assertEqual(json.loads((output/'report/results.json').read_text())['points'],4)
            self.assertNotIn('not-a-real-key',(output/'run.json').read_text())
            before=len(fake.calls)
            runner.execute(args(folder,resume=True),server,'fixture/model')
            self.assertEqual(len(fake.calls),before)
            with self.assertRaisesRegex(ValueError,'configuration changed'):
                runner.execute(args(folder,resume=True,max_tokens=99),server,'fixture/model')

    def test_unsloth_native_load(self):
        with Fixture('unsloth') as fake:
            server=runner.Server(fake.url);models=server.models()
            self.assertEqual(server.backend,'unsloth')
            self.assertEqual([m['id'] for m in models],['fixture/model'])
            inference_model,_=server.load('fixture/model',32768,{'n_parallel':1},10)
            self.assertEqual(inference_model,'fixture/model')
            self.assertEqual(fake.calls[-1],('POST','/api/inference/load',{'model_path':'fixture/model','max_seq_length':32768,'n_parallel':1}))

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
            self.assertEqual((output/'Q01.answer.txt').read_text(),'Not JSON')
            result=json.loads((output/'report/results.json').read_text())
            self.assertEqual((result['points'],result['answered']),(0,1))

    def test_truncation_recorded_zero_credit_and_retry_archived(self):
        with Fixture(behavior='truncated') as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url);server.models()
            runner.execute(args(folder,only='Q01'),server,'fixture/model')
            output=Path(folder)
            self.assertEqual(json.loads((output/'Q01.json').read_text())['status'],'truncated')
            self.assertEqual(json.loads((output/'report/results.json').read_text())['points'],0)
            fake.behavior='normal'
            runner.execute(args(folder,only='Q01',resume=True),server,'fixture/model')
            self.assertEqual(json.loads((output/'report/results.json').read_text())['points'],2)
            self.assertEqual(len(list((output/'attempts').glob('Q01-*'))),1)

    def test_broken_stream_stops_before_next_question(self):
        with Fixture(behavior='broken') as fake,tempfile.TemporaryDirectory(dir=runner.ROOT) as folder,contextlib.redirect_stdout(io.StringIO()):
            server=runner.Server(fake.url);server.models()
            with self.assertRaises(runner.ApiError):runner.execute(args(folder),server,'fixture/model')
            self.assertEqual(len([1 for v,p,b in fake.calls if p=='/v1/chat/completions']),1)
            self.assertFalse((Path(folder)/'Q02.json').exists())
            self.assertEqual(json.loads((Path(folder)/'Q01.json').read_text())['status'],'incomplete')

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
            self.assertIn('https://github.com/Prism77Proton/Model-Test-v2/issues/new',page)
            self.assertNotIn('<script',page)


if __name__=='__main__':unittest.main()
