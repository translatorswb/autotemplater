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

Transcribe with remotely running [ASR-API](https://github.com/translatorswb/ASR-API)
```
python autotemplater.py -i audio.wav -x -l en -u <remote-asr-api-endpoint>
```

Transcribe with Azure speech SDK
```
python autotemplater.py -i audio.wav -l en-US -a <azure-subscription-key> -r <azure-region>
```

Specify output directory (by default, output files are placed to where the input audio is located)
```
python autotemplater.py -i audio.wav -o <output-directory-path>
```

### Template options

Take turn on segment (`-t segment`) is selected by default. A timestamp is inserted everytime a speech segment is detected. For example: 
```
00:00:00 : hi and welcome back to the history podcast
00:00:03 : this week we got something a little bit different
00:00:05 : we have our guest here with us
00:00:12 : hello nice to be here
00:00:14 : nice to have you
```

Take turn on speaker change (`-t speaker`) will put timestamps everytime a speaker changes. For example:
```
00:00:00 : hi and welcome back to the history podcast this week we got something a little bit different we have our guest here with us
00:00:12 : hello nice to be here
00:00:14 : nice to have you
```

Using `-s` or `--sid` will insert speaker labels to each turn:
```
00:00:00 (A): hi and welcome back
00:00:03 (B): hello nice to be here
```
