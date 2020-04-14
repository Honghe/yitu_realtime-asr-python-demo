import json
import time

from flask import Flask
from flask import Response
from flask import render_template

app = Flask(__name__)

LOGCMD_SUCC = 0
LOGCMD_FAIL = 1
LOGCMD_QUIT = 2

iq = None


def eventStream():
    while True:
        logcmd, command, text = iq.get()
        if logcmd == LOGCMD_QUIT:
            break
        else:
            # wait for source data to be available, then push it
            msg = json.dumps([command, text], ensure_ascii=False)
            # print('msg {}'.format(msg))
            yield 'data: {}\n\n'.format(msg)


def get_message():
    '''this could be any function that blocks until data is ready'''
    time.sleep(1.0)
    s = time.ctime(time.time())
    return s


@app.route('/')
def hello_world():
    return render_template('index.html')


@app.route('/stream')
def stream():
    return Response(eventStream(), mimetype="text/event-stream")


def run(msg_queue):
    global iq
    iq = msg_queue
    return app.run(debug=False)


if __name__ == '__main__':
    run()
