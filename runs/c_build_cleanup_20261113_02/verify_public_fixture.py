"""Compare scan hits to the exact public upstream TLS fixture without printing it."""
from pathlib import Path
import urllib.request,json,hashlib,re
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
commit='b19bce971e82f2497d67fdacdeca8db08ae0ba56'
url=f'https://raw.githubusercontent.com/sphinx-doc/sphinx/{commit}/tests/certs/cert.pem'
raw=urllib.request.urlopen(url,timeout=25).read()
pattern=rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'
public=re.search(pattern,raw).group()
pre=json.loads((OUT/'publication_preflight.json').read_text(encoding='utf-8'));findings=[]
for row in pre['credential_findings']:
    p=ROOT/row['path'];blocks=re.findall(pattern,p.read_bytes());assert len(blocks)==1
    normalized=re.sub(rb'(?m)^\+',b'',blocks[0]).replace(b'\r\n',b'\n')
    assert normalized==public.replace(b'\r\n',b'\n'),row['path']
    findings.append({'path':row['path'],'file_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'kind':'private_key','public_fixture_match':True})
record={'source_url':url,'upstream_commit':commit,'public_fixture_sha256':hashlib.sha256(raw).hexdigest(),'private_block_normalized_sha256':hashlib.sha256(public).hexdigest(),'findings':findings,'interpretation':'Exact upstream Sphinx localhost TLS test certificate fixture. No project credentials.'}
with (OUT/'public_fixture_credential_review.json').open('x',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False,indent=2)
print(json.dumps({'matched_upstream_public_fixtures':len(findings),'upstream_commit':commit}))
