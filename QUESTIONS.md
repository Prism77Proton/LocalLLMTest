# Deterministic Model Test 50 — v2

Answer ONE supplied question at a time in a fresh context. No tools are required.
Output exactly one JSON object on one line: {"id":"Qnn","answer":{...}}.
Use the exact two answer field names specified by the question. No prose or Markdown.
Optional top-level "rationale" may contain a string; it is preserved but NEVER scored.
Use JSON booleans true/false, not strings. Numeric answers must be JSON integers;
no decimal or exponential notation is accepted. Rationals are REDUCED strings "n/d"
with positive denominator, including "0/1" and integral values like "6/1".
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


## Q01. Truth assignments

A says B and C have the same type. B says D is a liar. C says at least one of A,B is truthful. D says exactly two of A,B,C are truthful. Each person's truth type equals the truth value of their statement.

Answer fields:
- `assignments`: All [A,B,C,D] Boolean vectors, lexicographically sorted (false before true).
- `count`: Number of consistent assignments (integer).


## Q02. Shared diagnostic batch

Disease prevalence 1/100. A batch is defective with probability 1/10 independently of disease; defective tests are always positive. Otherwise tests are conditionally independent with sensitivity 19/20 and false-positive rate 1/50. Two tests use the SAME batch.

Answer fields:
- `posterior`: P(disease | both positive), rational string.
- `healthy_double_positive`: P(both positive | healthy), rational string.


## Q03. Causal bounds

P(X=0,Y=0)=P(X=1,Y=1)=1/2. Binary potential outcomes obey consistency only. Find sharp bounds on E[Y(1)-Y(0)].

Answer fields:
- `lower`: Rational string.
- `upper`: Rational string.


## Q04. Unsatisfiable core certificate

Integers x,y,z in {0,1,2}. C1:x!=y; C2:y!=z; C3:z!=x; C4:x+y+z=2.

Answer fields:
- `core`: Indices of the smallest unsatisfiable constraint set, ascending integers 1..4.
- `removal_witnesses`: For each removed core member, in core order, the lexicographically SMALLEST satisfying [x,y,z] for all remaining core members.


## Q05. Robust sensors

Reports:1,2,3,10,11,12,13. At most two arbitrary; all others within 5 inclusive of one real theta.

Answer fields:
- `feasible`: Entire feasible set as ascending numbers (it is finite).
- `minimax`: [optimal real estimate, worst absolute error].


## Q06. Exactly once

External payment API: no idempotency, no query, no shared Redis transaction. Ambiguous timeouts and crashes anywhere; eventual availability. Require eventual payment AND no duplicate effect. Choose a sufficient extra capability: A=separate success log after charge; B=durable atomic effect deduplication by stable key with replayable outcome; C=random retry delay.

Answer fields:
- `possible_now`: Boolean.
- `sufficient_capability`: One string: A, B or C.


## Q07. Linearizable history

Register starts0. W1:[0,4] writes1; W2:[1,2] writes2; R1:[3,5] reads1; R2:[4.5,6] reads2. Then modify ONLY R2 invocation to3.5. Linearization respects real-time nonoverlap.

Answer fields:
- `original`: Boolean: original linearizable?
- `modified_order`: Lexicographically smallest valid operation-name order for modified history (R1<R2<W1<W2).


## Q08. Optimal WorkGraph

One nonpreemptive Worker starts0, no idle required. Items (duration,weight,predecessors): A(2,1,[]), B(1,4,[]), C(3,1,[]), D(2,2,[A]), E(2,8,[A,B]), F(1,2,[C]), G(2,3,[D,E]), H(1,1,[F,G]). Minimize weighted completion sum.

Answer fields:
- `order`: Lexicographically first optimal array of item names.
- `objective`: Minimum weighted completion sum, integer.


## Q09. Quantifiers

Is forall runs r exists schema s forall ops in r validates(s,op) equivalent to exists s forall r forall ops validates(s,op)? Runs must be nonempty; schema set nonempty.

Answer fields:
- `equivalent`: Boolean.
- `minimum_counterexample`: [number of runs, number of schemas], minimize each.


## Q10. Quorums

7 replicas, at most2 Byzantine. Any write/write and read/write quorum pair must intersect in an honest replica. Minimize max(w,r).

Answer fields:
- `optimal`: [w,r] integers.
- `intersection_alone_linearizable`: Boolean: do these intersections ALONE specify a linearizable protocol?


## Q11. Pairwise independence

X,Y,Z fair bits, each pair independent; no mutual independence. Bound P(111).

Answer fields:
- `lower`: Rational string.
- `upper`: Rational string.


## Q12. Testing limits

Deterministic function domain: all finite byte strings; outputs Boolean. A finite test suite matches a reference. Then restrict input domain to ALL byte strings length<=2 and exhaustively test.

Answer fields:
- `finite_suite_proves_original`: Boolean.
- `restricted_domain_size`: Exact integer input count including empty string.


## Q13. Rewriting

Rules ab->baa and b->empty, applied anywhere to finite strings over a,b. Is every rewrite sequence terminating? Enumerate all irreducible descendants of input ab.

Answer fields:
- `all_terminate`: Boolean.
- `normal_forms_ab`: Lexicographically sorted array of distinct strings.


## Q14. Banker

Total resources(3,3). Allocated P1(1,0),P2(0,1),P3(1,1). Maxima P1(3,1),P2(1,3),P3(2,2).

Answer fields:
- `safe_sequence`: Lexicographically smallest safe process-name array for current state.
- `grant_p1_one_r`: Boolean under Banker criterion.


## Q15. Micro encoding

Fixed request-independent dictionary. Arbitrary uniform256-bit requests. External framing permits all binary strings length<=255. Separately require prefix-free codes.

Answer fields:
- `codeword_deficit`: Integer: number of requests minus number of available externally framed codewords.
- `minimum_prefix_mean_bits`: Rational string: minimum expected prefix-free length.


## Q16. DAG admission trace

limit=2. Ready admission lexical, refill after processing an entire completion batch, reject failures before refill. A,B initially ready. C dependsA; D dependsB. A,B admitted t0. B completes t1; D completes t2; A completes t3; C completes t4. Separate run: A and B fail in SAME observed batch.

Answer fields:
- `admission`: Array of admitted names in chronological admission order.
- `propagated_failure`: Name whose failure must propagate in separate run (lexical tie rule).


## Q17. Filesystem containment

Choose all designs sufficient against intermediate symlink swaps (no directory reparenting or malicious staging changes; trusted root/staging dirs). A=resolve/check then path write; B=O_NOFOLLOW on final component only; C=pin root fd, no-follow each component, exclusive fresh inode in trusted staging and dir-relative rename; D=string startswith(root).

Answer fields:
- `safe_designs`: Ascending array of design letters.
- `hardlink_truncation_safe`: Boolean: is opening/truncating an existing final hardlinked inode sufficient to avoid modifying an external inode?


## Q18. Snapshot cycle

Capsules read OLD snapshot. A reads config and writes port; B reads port and writes adapter; C reads adapter and writes config. Serialization edge reader->other-writer.

Answer fields:
- `edges`: Lexicographically sorted arrays [from,to].
- `serializable`: Boolean.


## Q19. Commit recovery

Durable immutable PREPARED record contains base B and candidate C. Git CAS B->C succeeded, process crashed before Redis finalize. Branch is now D, a descendant of C; no force resets allowed. Actions: A=apply patch again; B=finalize receipt for C; C=reset branch to B.

Answer fields:
- `action`: One action letter.
- `cross_store_atomic_visibility`: Boolean: does this protocol give simultaneous atomic Git+Redis visibility?


## Q20. SingleFlight

One loop; one live shared task per key. Each caller awaits asyncio.shield(task). Waiters A,B share keyK. A cancels while task running, B remains. Cleanup callback deletes registry entry only if its value is the completed task. A stale callback runs after a NEW task was installed.

Answer fields:
- `shared_task_cancelled`: Boolean: does cancellation of A alone cancel the shared task?
- `stale_callback_deletes_new`: Boolean.


## Q21. JSON Lines bytes

Strict UTF-8 JSONL parser, max4 raw bytes per record excluding LF but INCLUDING CR before optional CRLF stripping. Strict JSON rejects NaN. Input records separately: bytes for 1234+LF; 1234+CR+LF; JSON string containing é+LF (UTF-8); NaN+LF.

Answer fields:
- `accepted`: Boolean array for the four records.
- `unicode_record_bytes`: Raw byte count excluding LF for the third record.


## Q22. Relevant negative cycles

Directed weighted edges:0->1(1),1->2(-2),2->1(1),0->3(5),3->4(2). Source0. Shortest walk distances; a reachable negative cycle matters only if it can reach target.

Answer fields:
- `to_4`: Integer shortest distance before adding any edge.
- `to_4_after_edge`: After adding2->4(0), use integer, null for unreachable, or string -inf.


## Q23. Generator trace

Python 3.12+ code:

def inner():
    try:
        yield 1
        yield 2
    finally:
        print('inner-finally')

def outer():
    try:
        try:
            yield from inner()
        except ValueError:
            print('caught')
            yield 9
    finally:
        print('outer-finally')

g = outer()
print(next(g))
print(g.throw(ValueError()))
g.close()


Answer fields:
- `stdout`: Array of output line STRINGS in order.
- `inner_second_yield_reached`: Boolean.


## Q24. Tombstone ranking

Rows(resource,version,event,deleted,payload): (a,1,10,false,old),(a,2,11,true,gone),(b,2,20,false,left),(b,2,21,false,right),(c,3,30,false,new). cutoff2. Select latest by version DESC,event DESC per resource, THEN filter deleted. Sort output by resource.

Answer fields:
- `visible`: Array of [resource,payload].
- `filter_deleted_first_resurrects`: Sorted array of resources incorrectly resurrected by filtering tombstones before ranking.


## Q25. Write skew

Two doctors initially on call. Each snapshot transaction reads both, and if another is on-call turns ONLY its own row off. Both read before either commits. Ordinary snapshot isolation, no shared locks. Then choose sufficient remedies: A=true serializable plus retry; B=own-row locks only; C=shared guard row locked before a fresh READ COMMITTED read and held through commit.

Answer fields:
- `both_can_commit_off`: Boolean.
- `sufficient_remedies`: Sorted letters.


## Q26. Expression evaluator

Python arithmetic precedence; whitelist finite float literals, +,-,*,/,**, unary+/- and sqrt/sin/log bare one-argument calls. Every literal<=1e6 abs, every result<=1e12 abs, exponent abs<=10. Reject bools, names, attributes, domains, nonfinite results. Evaluate independently: -2**2; 2**3**2; sqrt(9)+sin(0); 1/0; True; (-1)**0.5; 2**11.

Answer fields:
- `outcomes`: Array of number results or string ERROR.
- `power_associativity`: String left or right.


## Q27. Process timeout

Linux parent P starts in new session/process group id P. P spawns child C in SAME group; C retains stdout. P exits at0.1s; C still running at deadline1s. Deadline applies until P exited AND streams EOF. Group TERM at1s; C ignores TERM. KILL after grace0.2s. No escapes, all killable/reapable.

Answer fields:
- `signals`: Array [time in milliseconds, signal name, target kind], target kind string process_group.
- `return_at_parent_exit`: Boolean: may runner return at0.1s with successful complete capture?


## Q28. Closable queue

Capacity1 FIFO contains x. close() occurs; then get(), get(), put(y). Closed is terminal for new puts; existing items drain. Separate full queue has a blocked producer; close() must wake it.

Answer fields:
- `results`: Strings for three operations: returned item or Closed.
- `blocked_producer_wakes`: Boolean.


## Q29. Runtime validation

External plain or null-prototype JS object: exact own keys kind,paths; kind='scan'; paths dense array of nonempty strings (whitespace counts nonempty). Reject symbols, extras, sparse holes, inherited-only keys. Candidates: A={kind:'scan',paths:[' ']}; B=same plus own Symbol key; C=paths array length1 with a hole; D=null-prototype object with kind:'scan',paths:['x']; E=paths:[''].

Answer fields:
- `accepted`: Sorted candidate letters.
- `array_every_detects_holes`: Boolean: does every(callback) necessarily visit missing indices?


## Q30. C17 semantics

Classify A=printf('%d %d',i++,i++) (assume valid double-quoted format); B=UINT_MAX+1u; C=dereference one-past int[2]; D=INT_MIN/-1 on two's-complement int. Classifications exactly UB or defined. Then consider D on permitted C17 symmetric signed range INT_MIN=-INT_MAX.

Answer fields:
- `classifications`: Strings for A,B,C,D.
- `symmetric_d_result`: String INT_MAX or UB.


## Q31. Lazy median storage

Sliding median uses two heaps and lazy deletion with k=3, no physical rebuilding. Feed strictly increasing stream of unbounded length n. Choose repair: A=drop multiplicities via set; B=when physical entries>3k rebuild from exact current deque incl duplicates and clear tombstones; C=keep only increasing values.

Answer fields:
- `unrebuilt_physical_bound`: String O(k) or Theta(n), worst case.
- `repair`: Repair letter.


## Q32. Overflow-free mulmod

Unsigned64 mathematical modular multiplication. a=18446744073709551614, b=18446744073709551613, m=18446744073709551557. Second fixture a=123,b=456,m=1. No intermediate wraparound in requested answers.

Answer fields:
- `result`: Exact first result integer.
- `mod_one`: Second result integer.


## Q33. Delta debugging

Ordered subsequences of [a,b,c,d]. Predicate fails EXACTLY on [a,b,c,d], [a,b], [c]. Current output[a,b]. 1-minimal means failing but no single deletion still fails. Global minimum means shortest failing subsequence of original.

Answer fields:
- `is_one_minimal`: Boolean for[a,b].
- `global_minimum`: Lexicographically first shortest failing array.


## Q34. Micro contract parser

Exact ASCII grammar: v1|mul|NAME:TYPE,NAME:TYPE->NAME:TYPE. NAME=[a-z][a-z0-9_]{0,7}; TYPE=i64 or f64; all3 names distinct; all3 types identical; full string consumed; no whitespace. Inputs A=v1|mul|x:i64,y:i64->z:i64; B=v1|mul|x:i64,x:i64->z:i64; C=v1|mul|x:f64,y:i64->z:f64; D=A followed by newline; E=v1|mul|a:f64,b:f64->c:f64. Runtime i64 product2^62*4.

Answer fields:
- `accepted`: Sorted letters.
- `runtime_product`: String OVERFLOW or integer result under checked i64.


## Q35. Stable roots

For quadratic coefficients(1,-10^16,1), stable q=-0.5*(b+copysign(sqrt(b*b-4*a*c),b)); roots q/a and c/q. Round the two exact real roots to ONE significant decimal digit, obtaining powers of10. What are those powers' exponents? Separately coefficients(1,0,0).

Answer fields:
- `root_scale_exponents`: Ascending two integer exponents (not floors of the unrounded logarithms).
- `zero_case_roots`: Sorted exact two numeric roots for separate fixture.


## Q36. Power tower

7^(7^7) mod1000; right associative. Also compute exponent7^7 mod400.

Answer fields:
- `residue`: Integer0..999.
- `exponent_mod_400`: Integer0..399.


## Q37. Improper integral

I=integral_0^infinity ln(x)*ln(1+x)/(1+x)^2 dx. Return coefficient c in I=c*pi^2. Also S=sum_{k>=1}1/[k(k+1)^2] in form a+b*pi^2.

Answer fields:
- `coefficient`: Rational string c.
- `series_coefficients`: [a,b] rational strings.


## Q38. Monic minimax quartic

On[-1,1], minimize sup abs(p) for monic quartic p. Give coefficients descending x^4..x^0 and norm.

Answer fields:
- `coefficients`: Five rational strings.
- `sup_norm`: Rational string.


## Q39. Pell certificate

Smallest positive Pell solution x^2-13y^2=1,y>0. Also give periodic continued fraction sqrt13=[a0;overline(period)].

Answer fields:
- `solution`: [x,y] integers.
- `period`: Periodic entries only, canonical shortest period starting immediately after a0.


## Q40. Random F2 matrix

6x6 matrix of independent fair F2 bits.

Answer fields:
- `rank_probabilities`: [P(rank6),P(rank5)] rational strings.
- `expected_nonzero_kernel`: Rational string; not expected nullity.


## Q41. Coin patterns

Fair independent coin tosses until first HTH or HHT as contiguous substring.

Answer fields:
- `hth_wins`: Rational probability string.
- `expected_tosses`: Rational string.


## Q42. Conditional exponential

Independent X,Y~Exp(1). E[X|X+Y>t]=(a*t^2+b*t+c)/(d*t+e), with primitive positive integer coefficients and gcd(a,b,c,d,e)=1.

Answer fields:
- `coefficients`: [a,b,c,d,e] integers.
- `at_zero`: Rational string.


## Q43. Concentrating mass

f_n(x)=n^2*x*(1-x)^n on[0,1].

Answer fields:
- `limits`: [pointwise limit at every x, limit integral f_n, limit integral x*f_n], rational strings.
- `integrable_dominator_exists`: Boolean: one integrable function bounds all f_n.


## Q44. Jordan growth

A4x4 has ones on diagonal and immediately above, zeros elsewhere. Compute A^10. Also limit ||A^n||_2/n^3.

Answer fields:
- `power_10`: 4x4 array of integers row-major.
- `norm_limit`: Rational string.


## Q45. Constrained product

x,y,z>=0; x+y+z=6; x^2+y^2+z^2=14. Write each extreme of xyz in basis1,sqrt3: a+b*sqrt3. All ordered triples count separately.

Answer fields:
- `extrema_coefficients`: [[a_min,b_min],[a_max,b_max]], rational strings.
- `ordered_equality_counts`: [number minimizing triples, number maximizing triples], integers.


## Q46. Circular strings

Length20 binary strings, exactly6 ones, no adjacent ones including cyclic boundary. Necklaces identify rotations, not reflections.

Answer fields:
- `labeled`: Integer count.
- `necklaces`: Integer count.


## Q47. Modular roots

All x in[0,4095] with x^2=1 mod4096.

Answer fields:
- `roots`: Ascending integer array.
- `count`: Integer.


## Q48. Minimal polynomial

alpha=sqrt2+sqrt3+sqrt5 overQ. Give its monic minimal polynomial and algebraic degree.

Answer fields:
- `coefficients`: Integer coefficients descending x^8..x^0, including zeros.
- `degree`: Integer.


## Q49. Expected determinant

A,B,C,D independent uniform[0,1]. U=AD has CDF F(t)=t(1-ln(t)),0<t<1.

Answer fields:
- `expected_abs_determinant`: E|AD-BC| rational string.
- `integrals`: [integral_0^1 F(t)dt, integral_0^1 F(t)^2 dt], rational strings.


## Q50. Sharp information inequality

For p,q in(0,1), natural-log Bernoulli KL D(p||q)>=C*(p-q)^2. Find largest universal C. Equality set in original domain, with that optimal C: A=p=q; B=p+q=1; C=p=1/2; D=never.

Answer fields:
- `sharp_constant`: Rational string.
- `equality_set`: One letter A,B,C,D.

