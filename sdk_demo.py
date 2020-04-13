#!/usr/bin/env python

from __future__ import division

import argparse
import collections
import threading
import time,io,wave,hashlib,hmac
import pyaudio


import six
from six.moves import queue


# ====================== speechsaas core import ===========================
import grpc
import asr_streaming_v6_pb2 as asr_pb
import asr_streaming_v6_pb2_grpc as asr_grpc
import concurrent
import long_stats
from threading import Thread
import multiprocessing
# ======================= speechsaas core import end ======================


PROD_ASRRT_URL = 'stream-asr-prod.yitutech.com:50051'
RATE = 16000
NUM_CHUNK = 10
CHUNK = RATE // NUM_CHUNK  # 100ms
DEVIDX = 7  # micarray:9; windows:1
NUM_CHANNELS = 1
AUDIO_ONE_SHOT = False
LOGCMD_SUCC = 0
LOGCMD_FAIL = 1
LOGCMD_QUIT = 2

APP_ID = '1403'
APP_KEY = b'0736aabbbbbf42458b68ba3e6aa75d9b'  #prod-env


class MicrophoneStream(object):
    """Opens a recording stream as a generator yielding the audio chunks."""
    def __init__(self, rate, chunk, devidx=DEVIDX):
        self._rate = rate
        self._chunk = chunk
        self._devidx = devidx
        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.closed = True
        
        

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # The API currently only supports 1-channel (mono) audio
            # https://goo.gl/z757pE
            channels=NUM_CHANNELS, rate=self._rate,
            input=True, frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
            input_device_index=self._devidx,
        )

        self.closed = False

        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        self._audio_interface.terminate()

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream, into the buffer."""        
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self):        
        while not self.closed:            
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            #print('i am in generator',self.closed,chunk)
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:                
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break
            
            yield b''.join(data)




class ResumableMicrophoneStream(MicrophoneStream):
    """Opens a recording stream as a generator yielding the audio chunks."""
    def __init__(self, stream_id, rate, chunk_size, dev_idx=DEVIDX, max_replay_secs=5):
        super(ResumableMicrophoneStream, self).__init__(rate, chunk_size, dev_idx)
        self.stream_id = stream_id
        self._max_replay_secs = max_replay_secs

        # Some useful numbers
        # 2 bytes in 16 bit samples
        self._bytes_per_sample = 2 * 1  
        self._bytes_per_second = self._rate * self._bytes_per_sample
        self._bytes_per_chunk = (CHUNK * self._bytes_per_sample)
        self._chunks_per_second = (
                self._bytes_per_second // self._bytes_per_chunk)
        self._untranscribed = collections.deque(
                maxlen=self._max_replay_secs * self._chunks_per_second)
        
        
    def on_transcribe(self, end_time):
        while self._untranscribed and end_time > self._untranscribed[0][1]:
            self._untranscribed.popleft()

    def generator(self, resume=False):        
        total_bytes_sent = 0
        if resume:
            # Make a copy, in case on_transcribe is called while yielding them
            catchup = list(self._untranscribed)
            # Yield all the untranscribed chunks first
            for chunk, _ in catchup:
                yield chunk
        
        for byte_data in super(ResumableMicrophoneStream, self).generator():
            # Populate the replay buffer of untranscribed audio bytes
            total_bytes_sent += len(byte_data)
            chunk_end_time = total_bytes_sent / self._bytes_per_second
            yield byte_data


class SimulatedMicrophoneStream(ResumableMicrophoneStream):
    def __init__(self, audio_src, *args, **kwargs):
        super(SimulatedMicrophoneStream, self).__init__(*args, **kwargs)
        self._audio_src = audio_src           

    def _delayed(self, get_data):
        total_bytes_read = 0
        start_time = time.time()

        chunk = get_data(self._bytes_per_chunk)
        fixed_len = len(chunk)
        while chunk and not self.closed:
            total_bytes_read += len(chunk)
            expected_yield_time = start_time + (
                    total_bytes_read / self._bytes_per_second)
            now = time.time()
            if expected_yield_time > now:
                time.sleep(expected_yield_time - now)

            yield chunk
            chunk = get_data(self._bytes_per_chunk)
    
    
    def _stream_from_raw(self, audio_src):
        idx = 0
        while True:
            with open(audio_src, 'rb') as f:
                for chunk in self._delayed(
                        lambda b_per_chunk: f.read(b_per_chunk)):
                    yield chunk
            if AUDIO_ONE_SHOT:
                return
        
    def _stream_from_file(self, audio_src):
        wfp = wave.open(audio_src, 'rb')
        nf = wfp.getnframes()
        fr = wfp.getframerate()
        sample_audio_seconds = nf*1.0 / fr / wfp.getnchannels()
        audio_frames = wfp.readframes(nf)        
        print("data size:%d secs:%7.2f, frame rate:%d" % (len(audio_frames),sample_audio_seconds,fr))
        
        idx = 0
        while True:
            f = io.BytesIO(audio_frames)
            for chunk in self._delayed(
                    lambda b_per_chunk: f.read(b_per_chunk)):
                yield chunk            
            if AUDIO_ONE_SHOT:
                return
        

    def _thread(self):
        if self._audio_src[-3:] == 'wav':
            func = self._stream_from_file
        else:
            func = self._stream_from_raw
            
        for chunk in func(self._audio_src):
            self._fill_buffer(chunk,None,None,None)
        self._fill_buffer(None,None,None,None)

    def __enter__(self):        
        self.closed = False
        threading.Thread(target=self._thread).start()

        return self

    def __exit__(self, type, value, traceback):
        self.closed = True
        


def duration_to_secs(duration):
    return duration/1000
    
def listen_print_loop(responses, stream, iq):
    """Iterates through server responses and prints them.
    Same as in transcribe_streaming_mic, but keeps track of when a sent
    audio_chunk has been transcribed.
    """    
    total = 0
    start_ts = int(time.time()*1000) #+ label_ts[0]
    for r in responses:
        result = r.result
        if result.is_final:
            top_alternative = result.best_transcription
            txt = top_alternative.transcribed_text
            # Keep track of what transcripts we've received, so we can resume
            # intelligently when we hit the deadline
           
            curr_ts = int(time.time()*1000)
            lat = len(txt)*1.0 / ((curr_ts - start_ts)/1000.0)
            total += len(txt)
            start_ts = curr_ts
            print('stream %d speed:%7.2f,len:%d,transcribe:%s,total:%d\n' % 
                (stream.stream_id, lat, len(txt),top_alternative.transcribed_text,total))
            iq.put((LOGCMD_SUCC,lat,len(txt)))
        else:
            print('stream %d transcribe:%s\n' % (stream.stream_id, result.best_transcription.transcribed_text))
            
def make_request(mic_manager,audio_generator):
    speech_config = asr_pb.SpeechConfig(
        lang=asr_pb.SpeechConfig.MANDARIN, scene=asr_pb.SpeechConfig.GENERAL_SCENE, 
        custom_word = ['邓垦','乱人','捉摸','前呢','依图'],
        use_custom_words_id= ['131','query','226']
        )
    audio_config = asr_pb.AudioConfig(
        aue=asr_pb.AudioConfig.PCM)

    ssc = asr_pb.StreamingSpeechConfig(audio_config=audio_config, speech_config=speech_config)
    config_req = asr_pb.StreamingSpeechRequest(streaming_speech_config=ssc)
    yield config_req    
    with mic_manager as stream:
        while True:        
            for content in audio_generator:
                #print('uploading %d' % len(content))
                data = asr_pb.StreamingSpeechRequest(audio_data=content)
                yield data
    
def get_asrrt_client(url):
    channel = grpc.insecure_channel(url)
    return asr_grpc.SpeechRecognitionStub(channel),channel

def signature(api_id,api_ts,api_key):
    message = str.encode(api_id+str(api_ts))    
    xsign = hmac.new(api_key, message, digestmod=hashlib.sha256).hexdigest()
    return xsign
    
def worker(sample_rate, audio_src, dev_idx, stream_id, iq, asrurl):      
    speech_config = asr_pb.SpeechConfig(
        lang=asr_pb.SpeechConfig.MANDARIN,scene=asr_pb.SpeechConfig.GENERAL_SCENE)
    audio_config = asr_pb.AudioConfig(
        aue=asr_pb.AudioConfig.PCM)
    ssc = asr_pb.StreamingSpeechConfig(audio_config=audio_config,speech_config=speech_config)
    
    client,chn = get_asrrt_client(asrurl)
    
    if audio_src:
        mic_manager = SimulatedMicrophoneStream(
                audio_src, stream_id, sample_rate, sample_rate // 10)
    else:
        mic_manager = ResumableMicrophoneStream(
                stream_id, sample_rate, sample_rate // 10, dev_idx)
    
    print("start recording",id(mic_manager),audio_src)
    audio_generator = mic_manager.generator()
    
    ts=int(time.time())
    xsign = signature(APP_ID,ts,APP_KEY)
    value='%s,%d,%s'%(APP_ID,ts,xsign)
    metadata = [('x-api-key', value),]
    
        
    try:
        responses = client.RecognizeStream(make_request(mic_manager,audio_generator),metadata=metadata)
        listen_print_loop(responses, mic_manager, iq)    
    except KeyboardInterrupt:
        print('#%d catch KeyboardInterrupt' % stream_id)
        pass
    except Exception as e:
        print('worker has something wrong %s' % str(e))
    #print('closing channel')
    chn.close()
    time.sleep(1)
    print('worker %d exiting...' % stream_id)
    return True
    
    

def log_func(iq):
    long_stats.setup()
    try:
        while True:
            logcmd, lat, length = iq.get()            
            if logcmd == LOGCMD_QUIT:
                break
            elif logcmd == LOGCMD_FAIL:
                long_stats.log_fail('','error',0,0)
                pass
            else:
                long_stats.log_succ('','realtime',lat,length)
            pass
    except KeyboardInterrupt:
        print('catch keyboard inerrupt in log_func')
    except Exception as e:
        print('logging has wrong %s' % str(e)) 
    long_stats.teardown() 
    print("exit log_func")

    
def main(sample_rate, src_type, audio_src, dev_idx, num_clients, asrurl,waitsecs): 
    pool = multiprocessing.Pool(processes=num_clients)
    m = multiprocessing.Manager()
    iq = m.Queue()    
    
    #logging
    log_daemon = multiprocessing.Process(target = log_func, args=(iq,))
    log_daemon.start()     
    multiple_results = []
    
    if src_type == "file":
        audio_lst = audio_src.split(',')
        for i in range(num_clients):
            afn = i % len(audio_lst)
            multiple_results.append(pool.apply_async(worker, (sample_rate, audio_lst[afn], dev_idx, i, iq, asrurl)))
    elif src_type == "mic":
        for i in range(num_clients):
            multiple_results.append(pool.apply_async(worker, (sample_rate, None, dev_idx, i, iq, asrurl)))
    
    total = len(multiple_results)
    complete = 0
    start = int(time.time())    
    timeout = False
    
    while complete!=total:
        complete = 0
        for res in multiple_results:
            try:
                b = res.get(timeout = 100)
                if b:
                    complete+=1
            except multiprocessing.context.TimeoutError as e:
                pass
            # check time
            end = int(time.time())
            if end-start>waitsecs:  
                print('time is up')
                timeout = True
                break
        if timeout:
            break
    
    print('stop processing pool...')
    pool.terminate()    
    iq.put((LOGCMD_QUIT,0,0)) 
    log_daemon.join()
    

        
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--rate', default=16000, help='采样率', type=int)
    parser.add_argument('--audio_src', default='sample.raw',help='模拟音频流的文件路径')
    parser.add_argument('--src_type', default='file',help='模拟音频流的文件路径')
    parser.add_argument('--dev_idx', default=DEVIDX,help='音频设备的编号， 可以通过get_index.py脚本获取', type=int)
    parser.add_argument('--num_client', default=1,help='并发数',type=int)
    parser.add_argument('--asrurl', default=PROD_ASRRT_URL,help='转写服务的Endpoint')
    parser.add_argument('--time', default=900,type=int,help='测试时间限制')   
    args = parser.parse_args()
    main(args.rate, args.src_type, args.audio_src, args.dev_idx, args.num_client, args.asrurl,args.time)