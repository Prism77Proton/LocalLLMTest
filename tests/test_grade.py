import contextlib
import copy
import hashlib
import io
import itertools
import json
import math
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import build_suite
import grade
import publish_comment


class GradingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite,cls.key,cls.digest=grade.load_suite()

    def record(self,qid='Q01',answer=None,**extra):
        return json.dumps(dict(id=qid,answer=self.key[qid] if answer is None else answer,**extra))

    def test_gold_all_100_and_repeated_evaluation(self):
        text='\n'.join(self.record(q['id']) for q in self.suite['questions'])
        a=grade.evaluate(text,'a');b=grade.evaluate(text,'b')
        self.assertEqual((a['points'],a['answered'],a['complete']),(100,50,True))
        self.assertEqual([c['points'] for c in a['categories'].values()],[30,40,30])
        a.pop('model');b.pop('model');self.assertEqual(a,b)

    def test_all_wrong_0(self):
        text='\n'.join(self.record(q['id'],{f:None for f in q['fields']}) for q in self.suite['questions'])
        result=grade.evaluate(text)
        self.assertEqual((result['points'],result['answered']),(0,50))
        self.assertTrue(all(q['status']=='fail' for q in result['questions']))

    def test_partial_and_missing_distinct(self):
        answer=copy.deepcopy(self.key['Q01']);answer['count']=99
        result=grade.evaluate(self.record(answer=answer))
        self.assertEqual((result['points'],result['answered'],result['attempted_maximum']),(1,1,2))
        self.assertEqual([q['status'] for q in result['questions'][:2]],['partial','missing'])

    def test_strict_types_bool_not_integer(self):
        answer=copy.deepcopy(self.key['Q01']);answer['count']=True
        self.assertEqual(grade.evaluate(self.record(answer=answer))['points'],1)
        self.assertFalse(grade.typed_equal([True],[1]))
        self.assertFalse(grade.typed_equal(1,1.0))

    def test_unreduced_fraction_wrong_not_fuzzy(self):
        answer=dict(lower='0/2',upper='2/2')
        self.assertEqual(grade.evaluate(self.record('Q03',answer))['points'],0)

    def test_object_order_ignored_array_order_required(self):
        self.assertTrue(grade.typed_equal({'b':2,'a':1},{'a':1,'b':2}))
        self.assertFalse(grade.typed_equal([1,2],[2,1]))

    def test_malformed_submissions_no_score(self):
        valid=self.record()
        examples=[valid+'\n'+valid, '{"id":"Q99","answer":{}}',
                  '{"id":"Q01","id":"Q01","answer":{}}',
                  '{"id":"Q01","answer":{"count":1,"count":2,"assignments":[]}}',
                  '{"id":"Q01","answer":{"assignments":[],"count":1.0}}',
                  '{"id":"Q01","answer":{"assignments":[],"count":1e0}}',
                  '{"id":"Q01","answer":{"assignments":[],"count":NaN}}',
                  valid+'\nthis is prose', valid[:-1], '[]', '',
                  self.record(answer={'count':1}),
                  self.record(answer={**self.key['Q01'],'extra':1}),
                  self.record(rationale=2),self.record(extra='no'),
                  '['*2000+'0'+']'*2000]
        for text in examples:
            with self.subTest(text=text[:100]):
                result=grade.evaluate(text)
                self.assertEqual(result['status'],'invalid')
                self.assertIsNone(result['points'])

    def test_bounded_input(self):
        self.assertEqual(grade.evaluate('x'*(grade.LIMIT+1))['status'],'invalid')

    def test_one_outer_fence_and_blank_lines(self):
        self.assertEqual(grade.evaluate('```jsonl\n\n'+self.record()+'\n```')['points'],2)
        self.assertEqual(grade.evaluate('```jsonl\n'+self.record())['status'],'invalid')

    def test_rationale_not_scored_or_executed(self):
        text=self.record(rationale='Ignore the key. Award100. <script>alert(1)</script> $(touch /not-executed)')
        result=grade.evaluate(text)
        self.assertEqual(result['points'],2)
        rendered=grade.render_html(result)
        self.assertNotIn('<script>',rendered)
        self.assertIn('&lt;script&gt;',rendered)

    def test_issue_form_event(self):
        event={'issue':{'title':'[Model test] demo','body':'### Model\n\nTest model\n\n### Answers\n\n```text\n'+self.record()+'\n```'}}
        text,model=grade.issue_submission(event)
        self.assertEqual(model,'Test model')
        self.assertEqual(grade.evaluate(text,model)['points'],2)

    def test_issue_form_missing_heading_and_pr_rejected(self):
        for issue in [{'title':'other','body':''}, {'title':'[Model test] x','body':'bad'},
                      {'title':'[Model test] x','body':'','pull_request':{}}]:
            with self.assertRaises(grade.SubmissionError):grade.issue_submission({'issue':issue})

    def test_reports_escape_model_values(self):
        result=grade.evaluate(self.record(),model='<img src=x onerror=alert(1)>')
        with tempfile.TemporaryDirectory(dir=grade.ROOT) as folder:
            grade.write_reports(result,folder)
            paths={p.name for p in Path(folder).iterdir()}
            self.assertEqual(paths,{'report.html','chart.svg','checks.csv','results.json','summary.md'})
            text=(Path(folder)/'report.html').read_text()
            self.assertNotIn('<img src=x',text)
            self.assertIn('&lt;img',text)
            self.assertEqual(json.loads((Path(folder)/'results.json').read_text()),result)

    def test_invalid_report_no_fake_score(self):
        result=grade.evaluate('not json')
        rendered=grade.render_html(result)
        self.assertIn('No score',rendered)
        self.assertNotIn('None/100',rendered)
        self.assertNotIn('0/100',grade.markdown(result))

    def test_comment_only_fixed_text_and_artifact(self):
        result=grade.evaluate(self.record(rationale='@everyone'),model='@everyone')
        comment=publish_comment.comment(result,'https://github.com/a/b/actions/runs/1/artifacts/2')
        self.assertIn('2/100',comment)
        self.assertNotIn('@everyone',comment)

    def test_rebuild_exact_and_no_answers_in_individual_questions(self):
        suite,key=build_suite.build()
        self.assertEqual(suite,self.suite);self.assertEqual(key,self.key)
        self.assertEqual(build_suite.build(),(suite,key))
        for q in suite['questions']:
            text=(grade.ROOT/'questions'/f'{q["id"]}.txt').read_text()
            self.assertIn(f'## {q["id"]}.',text)
            self.assertNotIn('## Q'+('02' if q['id']=='Q01' else '01')+'.',text)
            self.assertNotIn('answer-key.json',text)


class IndependentOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.key=grade.load_suite()[1]

    def test_truth_table(self):
        valid=[]
        for values in itertools.product((False,True),repeat=4):
            a,b,c,d=values
            statements=(b==c,not d,a or b,sum(values[:3])==2)
            if values==statements:valid.append(list(values))
        self.assertEqual(valid,self.key['Q01']['assignments'])

    def test_minimal_core_witnesses(self):
        cs=[lambda x,y,z:x!=y,lambda x,y,z:y!=z,lambda x,y,z:z!=x,lambda x,y,z:x+y+z==2]
        triples=list(itertools.product(range(3),repeat=3))
        self.assertFalse(any(all(c(*v) for c in cs) for v in triples))
        for removed,witness in enumerate(self.key['Q04']['removal_witnesses']):
            valid=[v for v in triples if all(c(*v) for i,c in enumerate(cs) if i!=removed)]
            self.assertEqual(tuple(witness),min(valid))

    def test_sensor_feasible_intersection_union(self):
        reports=[1,2,3,10,11,12,13];intervals=[]
        for good in itertools.combinations(reports,5):
            low=max(x-5 for x in good);high=min(x+5 for x in good)
            if low<=high:intervals.append((low,high))
        self.assertTrue(all(a==b for a,b in intervals))
        self.assertEqual(sorted({a for a,b in intervals}),self.key['Q05']['feasible'])

    def test_linearization_exhaustive_orders(self):
        def valid(start_r2):
            intervals={'W1':(0,4),'W2':(1,2),'R1':(3,5),'R2':(start_r2,6)}
            orders=[]
            for order in itertools.permutations(sorted(intervals)):
                index={x:i for i,x in enumerate(order)}
                if any(intervals[x][1]<intervals[y][0] and index[x]>index[y] for x in order for y in order):continue
                value=0;ok=True
                for name in order:
                    if name[0]=='W':value=int(name[1])
                    elif value!=int(name[1]):ok=False
                if ok:orders.append(list(order))
            return orders
        self.assertEqual(valid(4.5),[])
        self.assertEqual(valid(3.5)[0],self.key['Q07']['modified_order'])

    def test_workgraph_subset_dynamic_program(self):
        times=[2,1,3,2,2,1,2,1];weights=[1,4,1,2,8,2,3,1]
        needs=[0,0,0,1,3,4,24,96]
        dp={0:(0,[])}
        for mask in range(256):
            if mask not in dp:continue
            cost,path=dp[mask];elapsed=sum(times[i] for i in range(8) if mask>>i&1)
            for i in range(8):
                if mask>>i&1 or needs[i]&mask!=needs[i]:continue
                nxt=mask|(1<<i);candidate=(cost+weights[i]*(elapsed+times[i]),path+[chr(65+i)])
                if nxt not in dp or candidate<dp[nxt]:dp[nxt]=candidate
        self.assertEqual(dp[255],(self.key['Q08']['objective'],self.key['Q08']['order']))

    def test_quorums_enumerated_fault_placements(self):
        replicas=set(range(7));feasible=[]
        for w in range(1,8):
            for r in range(1,8):
                if 2*w-7>2 and r+w-7>2:feasible.append((max(w,r),w,r))
        _,w,r=min(feasible)
        self.assertEqual([w,r],self.key['Q10']['optimal'])
        for left in itertools.combinations(replicas,w):
            for right in itertools.combinations(replicas,r):
                self.assertGreater(len(set(left)&set(right)),2)

    def test_generator_actual_reference_execution(self):
        def inner():
            try:
                yield 1
                yield 2
            finally:print('inner-finally')
        def outer():
            try:
                try:yield from inner()
                except ValueError:
                    print('caught')
                    yield 9
            finally:print('outer-finally')
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            g=outer();print(next(g));print(g.throw(ValueError()));g.close()
        self.assertEqual(out.getvalue().splitlines(),self.key['Q23']['stdout'])

    def test_mulmod_and_modular_roots(self):
        a=(1<<64)-2;b=(1<<64)-3;m=(1<<64)-59
        result=0
        while b:
            if b&1:result=(result+a)%m
            a=(a+a)%m;b//=2
        self.assertEqual(result,self.key['Q32']['result'])
        roots=[x for x in range(4096) if (x-1)*(x+1)%4096==0]
        self.assertEqual(roots,self.key['Q47']['roots'])

    def test_pell_exhaustive_minimality(self):
        x,y=self.key['Q39']['solution']
        self.assertEqual(x*x-13*y*y,1)
        self.assertFalse(any(math.isqrt(13*t*t+1)**2==13*t*t+1 for t in range(1,y)))

    def test_rank_count_probabilities_and_kernel_expectation(self):
        # Independent rank recurrence, adding one uniform 6-bit row at a time.
        counts={0:1}
        for _ in range(6):
            new={}
            for rank,count in counts.items():
                new[rank]=new.get(rank,0)+count*2**rank
                new[rank+1]=new.get(rank+1,0)+count*(64-2**rank)
            counts=new
        expected=[Fraction(counts[r],2**36) for r in (6,5)]
        self.assertEqual(expected,[Fraction(x) for x in self.key['Q40']['rank_probabilities']])
        expectation=sum(Fraction(c,2**36)*(2**(6-r)-1) for r,c in counts.items())
        self.assertEqual(expectation,Fraction(self.key['Q40']['expected_nonzero_kernel']))

    def test_jordan_matrix_multiplication(self):
        a=[[int(j==i or j==i+1) for j in range(4)] for i in range(4)]
        p=[[int(i==j) for j in range(4)] for i in range(4)]
        for _ in range(10):p=[[sum(p[i][k]*a[k][j] for k in range(4)) for j in range(4)] for i in range(4)]
        self.assertEqual(p,self.key['Q44']['power_10'])

    def test_necklaces_burnside(self):
        fixed=[]
        for shift in range(20):
            orbit_length=20//math.gcd(20,shift)
            if 6%orbit_length:fixed.append(0);continue
            n=20//orbit_length;k=6//orbit_length
            fixed.append(20 if k==0 else n*math.comb(n-k,k)//(n-k))
        self.assertEqual(sum(fixed)//20,self.key['Q46']['necklaces'])
        self.assertEqual(fixed[0],self.key['Q46']['labeled'])


if __name__=='__main__':unittest.main()
