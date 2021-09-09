# autotemplater
Create automatically diarized and transcribed oTranscribe templates

### Installation

```
pip install -r requirements.txt
```

### Usage

Only diarization:
```
python autotemplater.py -i audio.wav 
```

Transcribe with locally running [ASR-API](https://github.com/translatorswb/ASR-API)
```
python autotemplater.py -i audio.wav -x -l en
```

Transcribe with azure speeck SDK
```
python autotemplater.py -i audio.wav -l en-US -a <azure-subscription-key> -r <azure-region>
```
