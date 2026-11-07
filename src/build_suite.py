"""Build the revised, exact-output exam. No third-party dependencies."""
import itertools
import json
import math
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUESTIONS = []
KEY = {}


def add(n, title, task, fields, expected):
    qid = f"Q{n:02}"
    category = "Reasoning" if n <= 15 else "Code and systems" if n <= 35 else "Mathematics"
    assert len(fields) == len(expected) == 2 and set(fields) == set(expected)
    QUESTIONS.append(dict(id=qid, title=title, category=category, task=task, fields=fields))
    KEY[qid] = expected


def frac(x):
    x = F(x)
    return f"{x.numerator}/{x.denominator}"


def build():
    QUESTIONS.clear()
    KEY.clear()
    assignments = []
    for a, b, c, d in itertools.product((False, True), repeat=4):
        if (a == (b == c) and b == (not d) and c == (a or b)
                and d == (sum((a, b, c)) == 2)):
            assignments.append([a, b, c, d])
    add(1, "Truth assignments", "A says B and C have the same type. B says D is a liar. C says at least one of A,B is truthful. D says exactly two of A,B,C are truthful. Each person's truth type equals the truth value of their statement.",
        {"assignments": "All [A,B,C,D] Boolean vectors, lexicographically sorted (false before true).", "count": "Number of consistent assignments (integer)."},
        dict(assignments=assignments, count=len(assignments)))
    p1 = F(1, 10) + F(9, 10)*F(19, 20)**2
    p0 = F(1, 10) + F(9, 10)*F(1, 50)**2
    add(2, "Shared diagnostic batch", "Disease prevalence 1/100. A batch is defective with probability 1/10 independently of disease; defective tests are always positive. Otherwise tests are conditionally independent with sensitivity 19/20 and false-positive rate 1/50. Two tests use the SAME batch.",
        {"posterior": "P(disease | both positive), rational string.", "healthy_double_positive": "P(both positive | healthy), rational string."},
        dict(posterior=frac(F(1,100)*p1/(F(1,100)*p1+F(99,100)*p0)), healthy_double_positive=frac(p0)))
    add(3, "Causal bounds", "P(X=0,Y=0)=P(X=1,Y=1)=1/2. Binary potential outcomes obey consistency only. Find sharp bounds on E[Y(1)-Y(0)].", {"lower": "Rational string.", "upper": "Rational string."}, dict(lower="0/1", upper="1/1"))
    constraints = [lambda x,y,z:x!=y, lambda x,y,z:y!=z, lambda x,y,z:z!=x, lambda x,y,z:x+y+z==2]
    witnesses = []
    for removed in range(4):
        witnesses.append(next(list(v) for v in itertools.product(range(3), repeat=3) if all(c(*v) for i,c in enumerate(constraints) if i!=removed)))
    add(4, "Unsatisfiable core certificate", "Integers x,y,z in {0,1,2}. C1:x!=y; C2:y!=z; C3:z!=x; C4:x+y+z=2.",
        {"core": "Indices of the smallest unsatisfiable constraint set, ascending integers 1..4.", "removal_witnesses": "For each removed core member, in core order, the lexicographically SMALLEST satisfying [x,y,z] for all remaining core members."},dict(core=[1,2,3,4], removal_witnesses=witnesses))
    add(5, "Robust sensors", "Reports:1,2,3,10,11,12,13. At most two arbitrary; all others within 5 inclusive of one real theta.", {"feasible": "Entire feasible set as ascending numbers (it is finite).", "minimax": "[optimal real estimate, worst absolute error]."},dict(feasible=[6,7,8], minimax=[7,1]))
    add(6, "Exactly once", "External payment API: no idempotency, no query, no shared Redis transaction. Ambiguous timeouts and crashes anywhere; eventual availability. Require eventual payment AND no duplicate effect. Choose a sufficient extra capability: A=separate success log after charge; B=durable atomic effect deduplication by stable key with replayable outcome; C=random retry delay.", {"possible_now": "Boolean.", "sufficient_capability": "One string: A, B or C."},dict(possible_now=False,sufficient_capability="B"))
    add(7, "Linearizable history", "Register starts0. W1:[0,4] writes1; W2:[1,2] writes2; R1:[3,5] reads1; R2:[4.5,6] reads2. Then modify ONLY R2 invocation to3.5. Linearization respects real-time nonoverlap.", {"original": "Boolean: original linearizable?", "modified_order": "Lexicographically smallest valid operation-name order for modified history (R1<R2<W1<W2)."},dict(original=False,modified_order=["W2","R2","W1","R1"]))
    names = "ABCDEFGH"
    duration = dict(zip(names,[2,1,3,2,2,1,2,1]))
    weight = dict(zip(names,[1,4,1,2,8,2,3,1]))
    deps = dict(zip(names,["","","","A","AB","C","DE","FG"]))
    best = None
    for perm in itertools.permutations(names):
        seen=set(); t=0; cost=0
        for name in perm:
            if not set(deps[name])<=seen: break
            seen.add(name);t+=duration[name];cost+=t*weight[name]
        else:
            candidate=(cost,perm)
            if best is None or candidate<best: best=candidate
    add(8, "Optimal WorkGraph", "One nonpreemptive Worker starts0, no idle required. Items (duration,weight,predecessors): A(2,1,[]), B(1,4,[]), C(3,1,[]), D(2,2,[A]), E(2,8,[A,B]), F(1,2,[C]), G(2,3,[D,E]), H(1,1,[F,G]). Minimize weighted completion sum.", {"order": "Lexicographically first optimal array of item names.", "objective": "Minimum weighted completion sum, integer."},dict(order=list(best[1]),objective=best[0]))
    add(9, "Quantifiers", "Is forall runs r exists schema s forall ops in r validates(s,op) equivalent to exists s forall r forall ops validates(s,op)? Runs must be nonempty; schema set nonempty.", {"equivalent": "Boolean.", "minimum_counterexample": "[number of runs, number of schemas], minimize each."},dict(equivalent=False,minimum_counterexample=[2,2]))
    add(10, "Quorums", "7 replicas, at most2 Byzantine. Any write/write and read/write quorum pair must intersect in an honest replica. Minimize max(w,r).", {"optimal": "[w,r] integers.", "intersection_alone_linearizable": "Boolean: do these intersections ALONE specify a linearizable protocol?"},dict(optimal=[5,5],intersection_alone_linearizable=False))
    add(11, "Pairwise independence", "X,Y,Z fair bits, each pair independent; no mutual independence. Bound P(111).", {"lower": "Rational string.", "upper": "Rational string."},dict(lower="0/1",upper="1/4"))
    add(12, "Testing limits", "Deterministic function domain: all finite byte strings; outputs Boolean. A finite test suite matches a reference. Then restrict input domain to ALL byte strings length<=2 and exhaustively test.", {"finite_suite_proves_original": "Boolean.", "restricted_domain_size": "Exact integer input count including empty string."},dict(finite_suite_proves_original=False,restricted_domain_size=1+256+256**2))
    add(13, "Rewriting", "Rules ab->baa and b->empty, applied anywhere to finite strings over a,b. Is every rewrite sequence terminating? Enumerate all irreducible descendants of input ab.", {"all_terminate": "Boolean.", "normal_forms_ab": "Lexicographically sorted array of distinct strings."},dict(all_terminate=True,normal_forms_ab=["a","aa"]))
    add(14, "Banker", "Total resources(3,3). Allocated P1(1,0),P2(0,1),P3(1,1). Maxima P1(3,1),P2(1,3),P3(2,2).", {"safe_sequence": "Lexicographically smallest safe process-name array for current state.", "grant_p1_one_r": "Boolean under Banker criterion."},dict(safe_sequence=["P3","P1","P2"],grant_p1_one_r=False))
    add(15, "Micro encoding", "Fixed request-independent dictionary. Arbitrary uniform256-bit requests. External framing permits all binary strings length<=255. Separately require prefix-free codes.", {"codeword_deficit": "Integer: number of requests minus number of available externally framed codewords.", "minimum_prefix_mean_bits": "Rational string: minimum expected prefix-free length."},dict(codeword_deficit=1,minimum_prefix_mean_bits="256/1"))
    add(16, "DAG admission trace", "limit=2. Ready admission lexical, refill after processing an entire completion batch, reject failures before refill. A,B initially ready. C dependsA; D dependsB. A,B admitted t0. B completes t1; D completes t2; A completes t3; C completes t4. Separate run: A and B fail in SAME observed batch.", {"admission": "Array of admitted names in chronological admission order.", "propagated_failure": "Name whose failure must propagate in separate run (lexical tie rule)."},dict(admission=["A","B","D","C"],propagated_failure="A"))
    add(17, "Filesystem containment", "Choose all designs sufficient against intermediate symlink swaps (no directory reparenting or malicious staging changes; trusted root/staging dirs). A=resolve/check then path write; B=O_NOFOLLOW on final component only; C=pin root fd, no-follow each component, exclusive fresh inode in trusted staging and dir-relative rename; D=string startswith(root).", {"safe_designs": "Ascending array of design letters.", "hardlink_truncation_safe": "Boolean: is opening/truncating an existing final hardlinked inode sufficient to avoid modifying an external inode?"},dict(safe_designs=["C"],hardlink_truncation_safe=False))
    add(18, "Snapshot cycle", "Capsules read OLD snapshot. A reads config and writes port; B reads port and writes adapter; C reads adapter and writes config. Serialization edge reader->other-writer.", {"edges": "Lexicographically sorted arrays [from,to].", "serializable": "Boolean."},dict(edges=[["A","C"],["B","A"],["C","B"]],serializable=False))
    add(19, "Commit recovery", "Durable immutable PREPARED record contains base B and candidate C. Git CAS B->C succeeded, process crashed before Redis finalize. Branch is now D, a descendant of C; no force resets allowed. Actions: A=apply patch again; B=finalize receipt for C; C=reset branch to B.", {"action": "One action letter.", "cross_store_atomic_visibility": "Boolean: does this protocol give simultaneous atomic Git+Redis visibility?"},dict(action="B",cross_store_atomic_visibility=False))
    add(20, "SingleFlight", "One loop; one live shared task per key. Each caller awaits asyncio.shield(task). Waiters A,B share keyK. A cancels while task running, B remains. Cleanup callback deletes registry entry only if its value is the completed task. A stale callback runs after a NEW task was installed.", {"shared_task_cancelled": "Boolean: does cancellation of A alone cancel the shared task?", "stale_callback_deletes_new": "Boolean."},dict(shared_task_cancelled=False,stale_callback_deletes_new=False))
    add(21, "JSON Lines bytes", "Strict UTF-8 JSONL parser, max4 raw bytes per record excluding LF but INCLUDING CR before optional CRLF stripping. Strict JSON rejects NaN. Input records separately: bytes for 1234+LF; 1234+CR+LF; JSON string containing é+LF (UTF-8); NaN+LF.", {"accepted": "Boolean array for the four records.", "unicode_record_bytes": "Raw byte count excluding LF for the third record."},dict(accepted=[True,False,True,False],unicode_record_bytes=4))
    add(22, "Relevant negative cycles", "Directed weighted edges:0->1(1),1->2(-2),2->1(1),0->3(5),3->4(2). Source0. Shortest walk distances; a reachable negative cycle matters only if it can reach target.", {"to_4": "Integer shortest distance before adding any edge.", "to_4_after_edge": "After adding2->4(0), use integer, null for unreachable, or string -inf."},dict(to_4=7,to_4_after_edge="-inf"))
    add(23, "Generator trace", "Python 3.12+ code:\n\ndef inner():\n    try:\n        yield 1\n        yield 2\n    finally:\n        print('inner-finally')\n\ndef outer():\n    try:\n        try:\n            yield from inner()\n        except ValueError:\n            print('caught')\n            yield 9\n    finally:\n        print('outer-finally')\n\ng = outer()\nprint(next(g))\nprint(g.throw(ValueError()))\ng.close()\n", {"stdout": "Array of output line STRINGS in order.", "inner_second_yield_reached": "Boolean."},dict(stdout=["1","inner-finally","caught","9","outer-finally"],inner_second_yield_reached=False))
    add(24, "Tombstone ranking", "Rows(resource,version,event,deleted,payload): (a,1,10,false,old),(a,2,11,true,gone),(b,2,20,false,left),(b,2,21,false,right),(c,3,30,false,new). cutoff2. Select latest by version DESC,event DESC per resource, THEN filter deleted. Sort output by resource.", {"visible": "Array of [resource,payload].", "filter_deleted_first_resurrects": "Sorted array of resources incorrectly resurrected by filtering tombstones before ranking."},dict(visible=[["b","right"]],filter_deleted_first_resurrects=["a"]))
    add(25, "Write skew", "Two doctors initially on call. Each snapshot transaction reads both, and if another is on-call turns ONLY its own row off. Both read before either commits. Ordinary snapshot isolation, no shared locks. Then choose sufficient remedies: A=true serializable plus retry; B=own-row locks only; C=shared guard row locked before a fresh READ COMMITTED read and held through commit.", {"both_can_commit_off": "Boolean.", "sufficient_remedies": "Sorted letters."},dict(both_can_commit_off=True,sufficient_remedies=["A","C"]))
    add(26, "Expression evaluator", "Python arithmetic precedence; whitelist finite float literals, +,-,*,/,**, unary+/- and sqrt/sin/log bare one-argument calls. Every literal<=1e6 abs, every result<=1e12 abs, exponent abs<=10. Reject bools, names, attributes, domains, nonfinite results. Evaluate independently: -2**2; 2**3**2; sqrt(9)+sin(0); 1/0; True; (-1)**0.5; 2**11.", {"outcomes": "Array of number results or string ERROR.", "power_associativity": "String left or right."},dict(outcomes=[-4,512,3,"ERROR","ERROR","ERROR","ERROR"],power_associativity="right"))
    add(27, "Process timeout", "Linux parent P starts in new session/process group id P. P spawns child C in SAME group; C retains stdout. P exits at0.1s; C still running at deadline1s. Deadline applies until P exited AND streams EOF. Group TERM at1s; C ignores TERM. KILL after grace0.2s. No escapes, all killable/reapable.", {"signals": "Array [time in milliseconds, signal name, target kind], target kind string process_group.", "return_at_parent_exit": "Boolean: may runner return at0.1s with successful complete capture?"},dict(signals=[[1000,"TERM","process_group"],[1200,"KILL","process_group"]],return_at_parent_exit=False))
    add(28, "Closable queue", "Capacity1 FIFO contains x. close() occurs; then get(), get(), put(y). Closed is terminal for new puts; existing items drain. Separate full queue has a blocked producer; close() must wake it.", {"results": "Strings for three operations: returned item or Closed.", "blocked_producer_wakes": "Boolean."},dict(results=["x","Closed","Closed"],blocked_producer_wakes=True))
    add(29, "Runtime validation", "External plain or null-prototype JS object: exact own keys kind,paths; kind='scan'; paths dense array of nonempty strings (whitespace counts nonempty). Reject symbols, extras, sparse holes, inherited-only keys. Candidates: A={kind:'scan',paths:[' ']}; B=same plus own Symbol key; C=paths array length1 with a hole; D=null-prototype object with kind:'scan',paths:['x']; E=paths:[''].", {"accepted": "Sorted candidate letters.", "array_every_detects_holes": "Boolean: does every(callback) necessarily visit missing indices?"},dict(accepted=["A","D"],array_every_detects_holes=False))
    add(30, "C17 semantics", "Classify A=printf('%d %d',i++,i++) (assume valid double-quoted format); B=UINT_MAX+1u; C=dereference one-past int[2]; D=INT_MIN/-1 on two's-complement int. Classifications exactly UB or defined. Then consider D on permitted C17 symmetric signed range INT_MIN=-INT_MAX.", {"classifications": "Strings for A,B,C,D.", "symmetric_d_result": "String INT_MAX or UB."},dict(classifications=["UB","defined","UB","UB"],symmetric_d_result="INT_MAX"))
    add(31, "Lazy median storage", "Sliding median uses two heaps and lazy deletion with k=3, no physical rebuilding. Feed strictly increasing stream of unbounded length n. Choose repair: A=drop multiplicities via set; B=when physical entries>3k rebuild from exact current deque incl duplicates and clear tombstones; C=keep only increasing values.", {"unrebuilt_physical_bound": "String O(k) or Theta(n), worst case.", "repair": "Repair letter."},dict(unrebuilt_physical_bound="Theta(n)",repair="B"))
    m=(1<<64)-59; a=(1<<64)-2; b=(1<<64)-3
    add(32, "Overflow-free mulmod", f"Unsigned64 mathematical modular multiplication. a={a}, b={b}, m={m}. Second fixture a=123,b=456,m=1. No intermediate wraparound in requested answers.", {"result": "Exact first result integer.", "mod_one": "Second result integer."},dict(result=(a*b)%m,mod_one=0))
    add(33, "Delta debugging", "Ordered subsequences of [a,b,c,d]. Predicate fails EXACTLY on [a,b,c,d], [a,b], [c]. Current output[a,b]. 1-minimal means failing but no single deletion still fails. Global minimum means shortest failing subsequence of original.", {"is_one_minimal": "Boolean for[a,b].", "global_minimum": "Lexicographically first shortest failing array."},dict(is_one_minimal=True,global_minimum=["c"]))
    add(34, "Micro contract parser", "Exact ASCII grammar: v1|mul|NAME:TYPE,NAME:TYPE->NAME:TYPE. NAME=[a-z][a-z0-9_]{0,7}; TYPE=i64 or f64; all3 names distinct; all3 types identical; full string consumed; no whitespace. Inputs A=v1|mul|x:i64,y:i64->z:i64; B=v1|mul|x:i64,x:i64->z:i64; C=v1|mul|x:f64,y:i64->z:f64; D=A followed by newline; E=v1|mul|a:f64,b:f64->c:f64. Runtime i64 product2^62*4.", {"accepted": "Sorted letters.", "runtime_product": "String OVERFLOW or integer result under checked i64."},dict(accepted=["A","E"],runtime_product="OVERFLOW"))
    add(35, "Stable roots", "For quadratic coefficients(1,-10^16,1), stable q=-0.5*(b+copysign(sqrt(b*b-4*a*c),b)); roots q/a and c/q. Round the two exact real roots to ONE significant decimal digit, obtaining powers of10. What are those powers' exponents? Separately coefficients(1,0,0).", {"root_scale_exponents": "Ascending two integer exponents (not floors of the unrounded logarithms).", "zero_case_roots": "Sorted exact two numeric roots for separate fixture."},dict(root_scale_exponents=[-16,16],zero_case_roots=[0,0]))
    add(36, "Power tower", "7^(7^7) mod1000; right associative. Also compute exponent7^7 mod400.", {"residue": "Integer0..999.", "exponent_mod_400": "Integer0..399."},dict(residue=pow(7,7**7,1000),exponent_mod_400=pow(7,7,400)))
    add(37, "Improper integral", "I=integral_0^infinity ln(x)*ln(1+x)/(1+x)^2 dx. Return coefficient c in I=c*pi^2. Also S=sum_{k>=1}1/[k(k+1)^2] in form a+b*pi^2.", {"coefficient": "Rational string c.", "series_coefficients": "[a,b] rational strings."},dict(coefficient="1/6",series_coefficients=["2/1","-1/6"]))
    add(38, "Monic minimax quartic", "On[-1,1], minimize sup abs(p) for monic quartic p. Give coefficients descending x^4..x^0 and norm.", {"coefficients": "Five rational strings.", "sup_norm": "Rational string."},dict(coefficients=["1/1","0/1","-1/1","0/1","1/8"],sup_norm="1/8"))
    pell=next((math.isqrt(1+13*y*y),y) for y in itertools.count(1) if math.isqrt(1+13*y*y)**2==1+13*y*y)
    add(39, "Pell certificate", "Smallest positive Pell solution x^2-13y^2=1,y>0. Also give periodic continued fraction sqrt13=[a0;overline(period)].", {"solution": "[x,y] integers.", "period": "Periodic entries only, canonical shortest period starting immediately after a0."},dict(solution=list(pell),period=[1,1,1,1,6]))
    inv=math.prod(F(64-2**i,64) for i in range(6))
    rank5=math.prod(F((64-2**i)**2,32-2**i) for i in range(5))
    add(40, "Random F2 matrix", "6x6 matrix of independent fair F2 bits.", {"rank_probabilities": "[P(rank6),P(rank5)] rational strings.", "expected_nonzero_kernel": "Rational string; not expected nullity."},dict(rank_probabilities=[frac(inv),frac(rank5/2**36)],expected_nonzero_kernel="63/64"))
    add(41, "Coin patterns", "Fair independent coin tosses until first HTH or HHT as contiguous substring.", {"hth_wins": "Rational probability string.", "expected_tosses": "Rational string."},dict(hth_wins="1/3",expected_tosses="6/1"))
    add(42, "Conditional exponential", "Independent X,Y~Exp(1). E[X|X+Y>t]=(a*t^2+b*t+c)/(d*t+e), with primitive positive integer coefficients and gcd(a,b,c,d,e)=1.", {"coefficients": "[a,b,c,d,e] integers.", "at_zero": "Rational string."},dict(coefficients=[1,2,2,2,2],at_zero="1/1"))
    add(43, "Concentrating mass", "f_n(x)=n^2*x*(1-x)^n on[0,1].", {"limits": "[pointwise limit at every x, limit integral f_n, limit integral x*f_n], rational strings.", "integrable_dominator_exists": "Boolean: one integrable function bounds all f_n."},dict(limits=["0/1","1/1","0/1"],integrable_dominator_exists=False))
    matrix=[[math.comb(10,j-i) if 0<=j-i<=10 else 0 for j in range(4)] for i in range(4)]
    add(44, "Jordan growth", "A4x4 has ones on diagonal and immediately above, zeros elsewhere. Compute A^10. Also limit ||A^n||_2/n^3.", {"power_10": "4x4 array of integers row-major.", "norm_limit": "Rational string."},dict(power_10=matrix,norm_limit="1/6"))
    add(45, "Constrained product", "x,y,z>=0; x+y+z=6; x^2+y^2+z^2=14. Write each extreme of xyz in basis1,sqrt3: a+b*sqrt3. All ordered triples count separately.", {"extrema_coefficients": "[[a_min,b_min],[a_max,b_max]], rational strings.", "ordered_equality_counts": "[number minimizing triples, number maximizing triples], integers."},dict(extrema_coefficients=[["6/1","-2/9"],["6/1","2/9"]],ordered_equality_counts=[3,3]))
    # Enumerate actual masks independently rather than relying on the gap formula.
    masks=[]
    for positions in itertools.combinations(range(20),6):
        mask=sum(1<<p for p in positions)
        if mask & (((mask<<1)&((1<<20)-1))|(mask>>19)) == 0:masks.append(mask)
    canonical={min(((v<<r)|(v>>(20-r)))&((1<<20)-1) for r in range(20)) for v in masks}
    add(46, "Circular strings", "Length20 binary strings, exactly6 ones, no adjacent ones including cyclic boundary. Necklaces identify rotations, not reflections.", {"labeled": "Integer count.", "necklaces": "Integer count."},dict(labeled=len(masks),necklaces=len(canonical)))
    roots=[x for x in range(4096) if x*x%4096==1]
    add(47, "Modular roots", "All x in[0,4095] with x^2=1 mod4096.", {"roots": "Ascending integer array.", "count": "Integer."},dict(roots=roots,count=len(roots)))
    add(48, "Minimal polynomial", "alpha=sqrt2+sqrt3+sqrt5 overQ. Give its monic minimal polynomial and algebraic degree.", {"coefficients": "Integer coefficients descending x^8..x^0, including zeros.", "degree": "Integer."},dict(coefficients=[1,0,-40,0,352,0,-960,0,576],degree=8))
    add(49, "Expected determinant", "A,B,C,D independent uniform[0,1]. U=AD has CDF F(t)=t(1-ln(t)),0<t<1.", {"expected_abs_determinant": "E|AD-BC| rational string.", "integrals": "[integral_0^1 F(t)dt, integral_0^1 F(t)^2 dt], rational strings."},dict(expected_abs_determinant="13/54",integrals=["3/4","17/27"]))
    add(50, "Sharp information inequality", "For p,q in(0,1), natural-log Bernoulli KL D(p||q)>=C*(p-q)^2. Find largest universal C. Equality set in original domain, with that optimal C: A=p=q; B=p+q=1; C=p=1/2; D=never.", {"sharp_constant": "Rational string.", "equality_set": "One letter A,B,C,D."},dict(sharp_constant="2/1",equality_set="A"))
    assert len(QUESTIONS)==50 and len(KEY)==50
    return dict(version="2.0.0", name="Deterministic Model Test 50", questions=QUESTIONS), KEY


INSTRUCTIONS = """Answer ONE supplied question at a time in a fresh context. No tools are required.
Output exactly one JSON object on one line: {\"id\":\"Qnn\",\"answer\":{...}}.
Use the exact two answer field names specified by the question. No prose or Markdown.
Optional top-level \"rationale\" may contain a string; it is preserved but NEVER scored.
Use JSON booleans true/false, not strings. Numeric answers must be JSON integers;
no decimal or exponential notation is accepted. Rationals are REDUCED strings \"n/d\"
with positive denominator, including \"0/1\" and integral values like \"6/1\".
Arrays must follow the order specified by each question. Object key order is ignored.
Each field earns exactly 1 point if its complete typed value matches the oracle,
otherwise 0. Each question has 2 fields: 50 questions, 100 points total.
Missing questions score 0 but are marked missing, not wrong. Partial runs are allowed.
Unknown/duplicate question IDs, duplicate JSON keys, invalid JSON, extra answer fields,
or missing answer fields invalidate the submission; they do not produce a numeric score.
Answer fields have no synonyms or implicit coercions. You may reason privately;
only the requested outputs are assessed. Keep the answer key out of model context.
This revised test checks finite outputs and certificates, not arbitrary proof quality
or the correctness of unrestricted implementations. Scores are NOT comparable to v1.
"""


if __name__ == "__main__":
    suite,key=build()
    (ROOT/'suite.json').write_text(json.dumps(suite,indent=2)+'\n')
    (ROOT/'answer-key.json').write_text(json.dumps(key,indent=2)+'\n')
    (ROOT.parent/'MODEL_INSTRUCTIONS.txt').write_text(INSTRUCTIONS)
    question_dir=ROOT.parent/'questions'
    question_dir.mkdir(exist_ok=True)
    blocks=[]
    for q in suite['questions']:
        block=f"## {q['id']}. {q['title']}\n\n{q['task']}\n\nAnswer fields:\n"+''.join(f"- `{k}`: {v}\n" for k,v in q['fields'].items())
        blocks.append(block)
        (question_dir/f"{q['id']}.txt").write_text(INSTRUCTIONS+'\n'+block+'\n')
    (ROOT.parent/'QUESTIONS.md').write_text('# Deterministic Model Test 50 — v2\n\n'+INSTRUCTIONS+'\n\n'+'\n\n'.join(blocks)+'\n')
    print('Built 50 questions and 100 exact field checks.')
