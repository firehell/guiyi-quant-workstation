"""Serve the blind page only, or validate the owner's exported review.

Import does not freeze labels, train a learner or promote a model.
"""
from __future__ import annotations

import argparse
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path

ANSWERS = {'TREND_UP', 'TREND_DOWN', 'RANGE', 'UNCERTAIN'}


def validate_review(key: dict, review: dict, label_version: str) -> dict:
    if (not isinstance(review, dict) or review.get('dataset_id') != key['dataset_id']
            or review.get('label_version') != label_version):
        raise ValueError('REVIEW_IDENTITY_MISMATCH')
    references = {s['id']: s for s in key['references']}
    answers = review.get('answers')
    if not isinstance(answers, dict) or any(sid not in references for sid in answers):
        raise ValueError('REVIEW_SAMPLE_INVALID')
    rows = []
    for sid, answer in answers.items():
        if (not isinstance(answer, dict) or answer.get('answer') not in ANSWERS
                or not isinstance(answer.get('note'), str) or len(answer['note']) > 4000):
            raise ValueError('REVIEW_ANSWER_INVALID')
        reference = references[sid]
        rows.append(dict(id=sid,symbol=reference['symbol'],frequency=reference['frequency'],
            reference=reference['reference'],owner_answer=answer['answer'],note=answer['note'],
            agrees=answer['answer']==reference['reference']))
    return dict(status='WAIT_OWNER_LABEL_DECISION',dataset_id=key['dataset_id'],label_version=label_version,
        reviewed=len(rows),remaining=len(references)-len(rows),
        owner_uncertain=sum(r['owner_answer']=='UNCERTAIN' for r in rows),
        agreements=sum(r['agrees'] for r in rows),
        by_frequency=dict(Counter(r['frequency'] for r in rows)),rows=rows,
        training_permitted=False)


def serve(directory: Path, port: int):
    run=json.loads((directory/'run.json').read_text())
    if run['status'] not in ('WAIT_LABEL_REVIEW', 'REVIEW_SAMPLES_INSUFFICIENT'):
        raise ValueError('REVIEW_NOT_READY')
    content=(directory/'index.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.split('?',1)[0] not in ('/', '/index.html'):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Content-Length',str(len(content)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(content)
        def log_message(self, *args):
            pass
    print(f'REVIEW_READY http://127.0.0.1:{port}/',flush=True)
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    server=commands.add_parser('serve')
    server.add_argument('--directory',type=Path,required=True)
    server.add_argument('--port',type=int,default=5176)
    review=commands.add_parser('summarize')
    review.add_argument('--directory',type=Path,required=True)
    review.add_argument('--answers',type=Path,required=True)
    review.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='serve':
        serve(args.directory,args.port)
    else:
        if args.answers.stat().st_size>1_000_000:
            raise ValueError('REVIEW_FILE_TOO_LARGE')
        run=json.loads((args.directory/'run.json').read_text())
        if run['status'] not in ('WAIT_LABEL_REVIEW','REVIEW_SAMPLES_INSUFFICIENT'):
            raise ValueError('REVIEW_NOT_READY')
        key=json.loads((args.directory/'review-key.json').read_text())
        if key['dataset_id']!=run['dataset_id']:
            raise ValueError('REVIEW_IDENTITY_MISMATCH')
        result=validate_review(key,json.loads(args.answers.read_text()),run['label_version'])
        with args.output.open('x') as handle:
            json.dump(result,handle,ensure_ascii=False,indent=2)
        print(json.dumps({k:result[k] for k in ('status','reviewed','remaining','agreements','owner_uncertain')}))


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error_type':type(exc).__name__}))
        raise SystemExit(2) from None
