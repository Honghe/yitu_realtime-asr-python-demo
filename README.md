# Python SDK Demo
`sdk_demo.py`提供了核心逻辑的实现示例，用户可选择使用音频文件输入，或者麦克风输入

`sample.raw`为音频文件实例，格式为PCM，码率16K，每个音频帧包含16Bits的数据。

`asr_streaming_v6_pb2_grpc.py` 和 `asr_streaming_v6_pb2.py` 为核心API，由`asr_streaming.proto`生成

# 运行环境安装
```
python3 -m venv venv
source /venv/bin/activate
pip install -r requirements.txt
```
若Anaconda环境`pyaudio`获取麦克风有问题，待解决。
# 运行Demo
```
python sdk_demo.py --help  
usage: sdk_demo.py [-h] [--rate RATE] [--audio_src AUDIO_SRC]
                   [--src_type SRC_TYPE] [--dev_idx DEV_IDX]
                   [--num_client NUM_CLIENT] [--asrurl ASRURL] [--time TIME]

optional arguments:
  -h, --help            show this help message and exit
  --rate RATE           采样率
  --audio_src AUDIO_SRC
                        模拟音频流的文件路径
  --src_type SRC_TYPE   模拟音频流的文件路径
  --dev_idx DEV_IDX     音频设备的编号， 可以通过get_index.py脚本获取
  --num_client NUM_CLIENT
                        并发数
  --asrurl ASRURL       转写服务的Endpoint
  --time TIME           测试时间限制

```


# 使用mic做音频源
1. 通过get_index.py脚本获取到自己音频设备的id号, 示例通过设备名想使用的是7号设备（或者使用系统默认的pulse）
```
python get_index.py 
ALSA lib pcm.c:2266:(snd_pcm_open_noupdate) Unknown PCM cards.pcm.rear
ALSA lib pcm.c:2266:(snd_pcm_open_noupdate) Unknown PCM cards.pcm.center_lfe
ALSA lib pcm.c:2266:(snd_pcm_open_noupdate) Unknown PCM cards.pcm.side
ALSA lib pcm_route.c:867:(find_matching_chmap) Found no matching channel map
ALSA lib pcm_route.c:867:(find_matching_chmap) Found no matching channel map
ALSA lib pcm_route.c:867:(find_matching_chmap) Found no matching channel map
ALSA lib pcm_route.c:867:(find_matching_chmap) Found no matching channel map
Cannot connect to server socket err = No such file or directory
Cannot connect to server request channel
jack server is not running or cannot be started
JackShmReadWritePtr::~JackShmReadWritePtr - Init not done for 4294967295, skipping unlock
JackShmReadWritePtr::~JackShmReadWritePtr - Init not done for 4294967295, skipping unlock
Input Device id  0  -  HDA Intel PCH: ALC3234 Analog (hw:0,0)
Input Device id  1  -  HDA Intel PCH: ALC3234 Alt Analog (hw:0,2)
Input Device id  7  -  Jabra SPEAK 410 USB: Audio (hw:1,0)
Input Device id  8  -  sysdefault
Input Device id  14  -  pulse
Input Device id  16  -  default
```
2. python sdk_demo.py --dev_idx 7 --src_type mic