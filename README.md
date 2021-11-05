# autoTemplater
AutoTemplater is a command-line tool to complement speech audio transcription work done with the [oTranscribe tool](https://otranscribe.com/). 

Features: 
- Speaker diarization or speech activity detection with [pyannote](https://github.com/pyannote/pyannote-audio)
- Diarization revision and re-labeling
- Automatic speech recognition using [Microsoft Azure speech-to-text](https://docs.microsoft.com/en-us/azure/cognitive-services/speech-service/) or [TWB's ASR-API](https://github.com/translatorswb/ASR-API)
- Outputs oTranscribe templates (`.otr`) for post-editing
- Outputs SRT-format subtitles 

### Post-editing on oTranscribe

This tool outputs templates to be used in [otranscribe.com](https://otranscribe.com/). This is because Automatic speech recognition (ASR) makes errors, and they usually need to be post-edited to get accurate transcriptions. To do this, go to [otranscribe.com](https://otranscribe.com/), load your audio file and then import your template file (`.otr`) from the right hand menu. You can then easily post-edit while listening to your audio. 

![Template post-editing on oTranscribe](img/otranscribe_editing.png)

### Installation

```
git clone https://github.com/translatorswb/autotemplater.git
cd autotemplater
pip install -r requirements.txt
```

Note: If you want to use Azure without Azure SDK, you can remove the last line in the `requirements.txt` file. 

### Usage

Only speech activity detection, outputs an empty template with speech segments marked
```
python autotemplater.py -i audio.wav 
```

Only diarization, outputs an empty template with speech segments marked with their speaker labels
```
python autotemplater.py -i audio.wav -d
```

Transcribe with a locally running [ASR-API](https://github.com/translatorswb/ASR-API), takes default running location `http://127.0.0.1:8010/transcribe`
```
python autotemplater.py -i audio.wav -x api -l en
```

Transcribe with a remotely running [ASR-API](https://github.com/translatorswb/ASR-API)
```
python autotemplater.py -i audio.wav -x api -l en -u <remote-asr-api-endpoint>
```

Transcribe with Azure speech SDK
```
python autotemplater.py -i audio.wav -x azure -l en-US -a <azure-subscription-key> -r <azure-region>
```

Transcribe with Azure using REST API
```
python autotemplater.py -i audio.wav -x azure -l en-US -a <azure-subscription-key> -r <azure-region> -b
```

Using an output path other than the audio directory
```
python autotemplater.py -i audio.wav -o <output-directory-path>
```

### Speaker diarization revision

Speaker diarization step tends to detect more speakers than there is. A revision step is necessary to correct the automatically assigned labels. Once diarization is finished, you'll be asked to listen to sample segments placed in the project directory and place the correct speaker labels on each of them. Example:

```
...
Dumping raw diarization output ../test_audio/interview-rawdiarization.json
3 speakers detected, A: 76 segments B: 6 segments C: 33 segments
Do you want to revise speaker labels? (y for yes) >y<
Revise speaker samples from path revision/interview
A
revision/interview/A/278.52-280.71.wav
revision/interview/A/99.65-103.16.wav
revision/interview/A/371.61-374.60.wav
revision/interview/A/47.43-49.58.wav
revision/interview/A/397.36-399.41.wav

B
revision/interview/B/423.76-424.58.wav
revision/interview/B/420.81-423.24.wav
revision/interview/B/427.87-430.95.wav
revision/interview/B/414.21-420.58.wav
revision/interview/B/425.19-427.73.wav

C
revision/interview/C/123.76-124.58.wav
revision/interview/C/320.81-323.24.wav
revision/interview/C/227.87-230.95.wav
revision/interview/C/114.21-120.58.wav
revision/interview/C/325.19-327.73.wav

Please specify names for each label
A is... >Input here the name of speaker A e.g. Respondent<
B is... >Input here the name of speaker B e.g. Interviewer<
C is... >Input here the name of speaker C e.g. Interviewer<
Dumping mapping data ../test_audio/interview-spkrevisionmap.txt
Revised speaker labels
{'Interviewer': ['B'], 'Respondent': ['A', 'C']}
Dumping mapped diarization output ../test_audio/interview-reviseddiarization.json
Dumping diarized template ../test_audio/interview-diarization.otr
...
```

To skip this step, use the `-v` or `--skiprevision` flag and they'll keep the names assigned automatically (A,B,C etc.)

### Formatting options

Using `-s` or `--sid` will insert speaker labels at each turn (off by default):
```
00:00:00 (A): hi and welcome back
00:00:03 (B): hello nice to be here
```

Take turn on segment (`-t segment`) is selected by default. A timestamp is inserted for every speech segment seperated with a silence. For example: 
```
00:00:00 (A): hi and welcome back to the history podcast
00:00:03 (A): this week we got something a little bit different
00:00:05 (A): we have our guest here with us
00:00:12 (B): hello nice to be here
00:00:14 (A): nice to have you
```

Take turn on speaker change (`-t span`) will merge segments until they reach the specified span length and when there's a speaker change. For example:
```
00:00:00 (A): hi and welcome back to the history podcast this week we got something a little bit different we have our guest here with us
00:00:12 (B): hello nice to be here
00:00:14 (A): nice to have you
```

Span length (`spanlength`) is set to 30 seconds by default and can be changed using the `-n` flag. Example call:

```
python autotemplater.py -i audio.wav -x api -l en -t speaker -m 15
```

### Output files

Main output files are as follows:

- `audio-rawdiarization.otr`: oTranscribe template with timestamps only (no transcription)
- `audio-autotemplate.otr`: oTranscribe template with timestamps and transcription
- `audio-transcript.txt`:  Plain text transcript with timestamps
- `audio-subtitles.srt`: SRT format subtitles

Other output files for debugging purposes:

- `audio-rawdiarization.json`: Raw diarization output
- `audio-reviseddiarization.json`: Revised diarization output
- `audio-spkrevisionmap.json`: Speaker mapping after revision
- `audio-asr.json`: Transcribed speaker turn data

WARNING: These are also reutilized on consecutive runs of the same audio file. 
