# autoTemplater
Create automatically diarized and transcribed oTranscribe templates

### Installation

```
git clone https://github.com/translatorswb/autotemplater.git
cd autotemplater
pip install -r requirements.txt
```

### Usage

Only diarization
```
python autotemplater.py -i audio.wav 
```

Transcribe with locally running [ASR-API](https://github.com/translatorswb/ASR-API)
```
python autotemplater.py -i audio.wav -x api -l en
```

Transcribe with remotely running [ASR-API](https://github.com/translatorswb/ASR-API)
```
python autotemplater.py -i audio.wav -x api -l en -u <remote-asr-api-endpoint>
```

Transcribe with Azure speech SDK
```
python autotemplater.py -i audio.wav -x azure -l en-US -a <azure-subscription-key> -r <azure-region>
```

Using an output path other than the audio directory
```
python autotemplater.py -i audio.wav -o <output-directory-path>
```

### Speaker diarization revision

Speaker diarization step tends to detect more speakers than usual. A revision step is necessary to correct the automatically assigned labels. Once diarization is finished, you'll be asked to listen to sample segments placed in the project directory and place the correct speaker labels on each of them. Example:

```
...
Dumping raw diarization output ../test_audio/interview-rawdiarization.json
3 speakers detected
A: 76 segments
B: 6 segments
C: 33 segments
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
A is... >Respondent<
B is... >Interviewer<
C is... >Respondent<
Dumping mapping data ../test_audio/interview-spkrevisionmap.txt
Revised speaker labels
{'Interviewer': ['B'], 'Respondent': ['A', 'C']}
Dumping mapped diarization output ../test_audio/interview-reviseddiarization.json
Dumping diarized template ../test_audio/interview-diarization.otr
...
```

To skip this step, use the `-v` or `--skiprevision` flag.

### Template options

Using `-s` or `--sid` will insert speaker labels at each turn (off by default):
```
00:00:00 (A): hi and welcome back
00:00:03 (B): hello nice to be here
```

Take turn on segment (`-t segment`) is selected by default. A timestamp is inserted everytime a speech segment is detected. For example: 
```
00:00:00 (A): hi and welcome back to the history podcast
00:00:03 (A): this week we got something a little bit different
00:00:05 (A): we have our guest here with us
00:00:12 (B): hello nice to be here
00:00:14 (A): nice to have you
```

Take turn on speaker change (`-t speaker`) will put timestamps only when there's a speaker change. For example:
```
00:00:00 (A): hi and welcome back to the history podcast this week we got something a little bit different we have our guest here with us
00:00:12 (B): hello nice to be here
00:00:14 (A): nice to have you
```

### Output files

Main output files are as follows:

- `audio-rawdiarization.otr`: oTranscribe template with timestamps only (and without transcription)
- `audio-transcript.txt`:  Plain text transcript with timestamps
- `audio-autotemplate.otr`: oTranscribe template with timestamps and transcription

Other output files for debugging purposes:

- `audio-rawdiarization.json`: Raw diarization output
- `audio-reviseddiarization.json`: Revised diarization output
- `audio-spkrevisionmap.json`: Speaker mapping after revision

### Post-editing on oTranscribe

Automatic speech recognition (ASR) makes errors. If you want to do post-editing on the output, go to [otranscribe.com](https://otranscribe.com/), load your audio file and then import your template file (`.otr`). You can then easily post-edit while listening to your audio. 

![Template post-editing on oTranscribe](img/otranscribe_editing.png)
