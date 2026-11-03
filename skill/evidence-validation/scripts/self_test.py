from pathlib import Path
import tempfile,json,hashlib
from verify import compare,manifest,words
checks=[]
def test(name,fn,fail=False):
    try:fn()
    except (ValueError,OSError):
        if not fail:raise
    else:
        if fail:raise AssertionError(name+' should reject')
    checks.append(name)
test('equal',lambda:compare([1,[2.0]],[1,[2.0]]))
test('tolerance',lambda:compare([1.001],[1.0],.002))
test('value mismatch',lambda:compare([1.1],[1.0]),True)
test('shape mismatch',lambda:compare([[1]],[[1,2]]),True)
test('nonfinite',lambda:compare([float('nan')],[0]),True)
test('integer precision',lambda:compare([2**64],[2**64+1]),True)
test('boolean rejected',lambda:compare([True],[1]),True)
with tempfile.TemporaryDirectory() as td:
    d=Path(td);f=d/'x';f.write_text('00000001 ffffffff',encoding='utf8')
    test('hex exact',lambda:compare(words(f),[1,4294967295]))
    row={'path':'x','sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
    test('valid manifest',lambda:manifest(d,[row]))
    test('hash mismatch',lambda:manifest(d,[dict(row,sha256='0'*64)]),True)
    test('path escape',lambda:manifest(d,[dict(row,path='../x')]),True)
    test('duplicate path',lambda:manifest(d,[row,row]),True)
out=Path(__file__).resolve().parents[1]/'tests/RESULT.json';out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps({'status':'PASS','checks':checks,'count':len(checks),'scope':'only reusable validation tool; no DUT runs'},indent=2),encoding='utf8')
print('SKILL_SELF_TEST_PASS',len(checks))
