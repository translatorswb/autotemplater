# Creates automatically diarized and transcribed oTranscribe template using pyannote and ASR API or Azure 

import argparse
import sys
import torch
import time
import os
import wave
import json
import subprocess
import tempfile
import shutil
import requests
from pydub import AudioSegment

parser = argparse.ArgumentParser(description="oTranscribe template maker")
parser.add_argument('-i', '--audio', type=str, required=True, help='Input audio path')
parser.add_argument('-l', '--lang', type=str, help='Language')
parser.add_argument('-o', '--out', type=str, help='Output directory')
parser.add_argument('-p', '--punctoken', type=str, help='PunkProse token if sending to remote API')
parser.add_argument('-a', '--azuretoken', type=str, help='Azure token if sending to Azure ASR')
parser.add_argument('-x', '--useapi', action='store_true', help='Use ASR-API to transcribe')

API_TRANSCRIBE_URL = "http://127.0.0.1:8010/transcribe/short"
ASR_API_FLAG = 'api'
AZURE_ASR_FLAG = 'azure'

def timestamp_spanner(sec):
    ty_res = time.gmtime(sec)
    res = time.strftime("%H:%M:%S",ty_res)
    span_str = '<span class="timestamp" data-timestamp="%s">%s</span>'%(sec, res)
    return span_str

def get_speaker_turns(diarization_output):
    speaker_turns = []
    current_turn = {}
    current_speaker = ''
    for s in diarization_output:
        speaker_change = not s['label'] == current_speaker

        if speaker_change:
            #close current turn
            if current_turn:
                speaker_turns.append(current_turn)

            #open new turn
            current_turn['start'] = s['segment']['start']
        else:
            current_turn['end'] = s['segment']['end']

        if current_turn:
            current_turn['end'] = s['segment']['end']
            speaker_turns.append(current_turn)
            
    return speaker_turns

# def transcribe_speaker_turns(speaker_turns, complete_audio, tmp_dir_path, service, azure_speech_config=None):
#     for t in speaker_turns:
#         t['text'] = get_transcription_of_chunk(complete_audio, t['start'], t['end'], tmp_dir_path, azure_speech_config)

def speaker_turns_to_otr(speaker_turns, output_path):
    otr_text = ""
    for t in speaker_turns:
        otr_text += timestamp_spanner(t['start']) + ' '
        
        if 'text' in t:
            otr_text += t['text']
        otr_text += '<br /><br />'
        
    otr_format_dict = {'text': otr_text, "media": "", "media-time":"0.0"}
    
    with open(output_path, 'w') as f:
        f.write(json.dumps(otr_format_dict))

def do_diarization(wav_path):
    from pyannote.core import Annotation, Segment
    from pyannote.audio.features import RawAudio

    file = {'audio': wav_path}
    pipeline = torch.hub.load('pyannote/pyannote-audio', 'dia')
    diarization = pipeline(file)
    diarization_dict = diarization.for_json()

    return diarization_dict

def audio_convert(audio_path):
    do_convert = False
    if os.path.splitext(audio_path)[1][1:] == 'wav':
        wav_path = audio_path
        try:
            wf = wave.open(wav_path, "rb")
            framerate = wf.getframerate()

            if wf.getnchannels() != 1:
                print("Wav not mono")
                do_convert = True
        except:
            do_convert = True
    else:
        wav_path = os.path.splitext(os.path.basename(audio_path))[0] + '.wav'
        if os.path.exists(wav_path):
            return audio_convert(wav_path)
        else:
            do_convert = True

    if do_convert:
        process = subprocess.call(['ffmpeg', '-loglevel', 'quiet', '-i',
                                        audio_path, '-ac', '1', wav_path])

        print("Audio converted to wav: ", wav_path)

        return wav_path
    else:
        return audio_path


def initialize_azure_config(subscription_id, lang_code, region="westeurope"):
    global speechsdk
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(subscription=subscription_id, region=region)
    speech_config.speech_recognition_language=lang_code

    return speech_config

def transcribe_with_azure(audio_path, speech_config):
    audio_input = speechsdk.AudioConfig(filename=audio_path)
    speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_input)

    result = speech_recognizer.recognize_once_async().get()
    return result.text

def timestamp_spanner(sec):
    ty_res = time.gmtime(sec)
    res = time.strftime("%H:%M:%S",ty_res)
    span_str = '<span class="timestamp" data-timestamp="%s">%s</span>'%(sec, res)
    return span_str

def initialize_api_config(lang, scorer='default'):
    return {'lang': lang, 'scorer':scorer}

def transcribe_with_asr_api(audio_path, config):
    payload={'lang': config['lang']}
    print(payload)
    headers = {}
    
    #Send to ASR API
    audio_filename = os.path.basename(audio_path)
    
    files=[('file',(audio_filename, open(audio_path,'rb'),'audio/wav'))]
    print(files)
    
    try:
        response = requests.request("POST", API_TRANSCRIBE_URL, headers=headers, data=payload, files=files)
    except Exception as e:
        print("ERROR: Cannot establish connection with ASR API")
        print(e)
        return ""
    
    if response.ok:
        response_dict = response.json()
        transcript = response_dict["transcript"]
    else:
        print("Cannot read response for file", audio_chunk_filename)
        transcript = ""
        
    return transcript

def get_transcription_of_chunk(complete_audio, start_sec, end_sec, chunk_path, service, speech_config=None):
    start_ms = start_sec * 1000
    end_ms = end_sec * 1000
    
    audio_segment = complete_audio[start_ms:end_ms]
    
    audio_chunk_filename = "%.2f"%start_sec + "-" + "%.2f"%end_sec + ".wav"
    audio_chunk_path = os.path.join(chunk_path, audio_chunk_filename)
    
    audio_segment.export(audio_chunk_path, format="wav")
    
    if service == ASR_API_FLAG:    
        transcript = transcribe_with_asr_api(audio_chunk_path, speech_config) 
    elif service == AZURE_ASR_FLAG:
        transcript = transcribe_with_azure(audio_chunk_path, speech_config)
    
    print("%.2f-%.2f: %s"%(start_sec, end_sec, transcript))
    return transcript

def main():
    args = parser.parse_args()

    audio_path = args.audio
    out_path = args.out
    lang = args.lang
    azure_token = args.azuretoken
    use_api = args.useapi

    if not audio_path:
        print("ERROR: Need input audio")
        sys.exit()

    if not out_path:
        out_path = os.path.dirname(audio_path)
        print("WARNING: Output directory not specified (-o). Will put results to audio directory.")
    else:
        if os.path.exists(out_path):
            if not os.path.isdir(out_path):
                print("ERROR: %s is a file"%out_path)
                sys.exit()
        else:
            os.mkdir(out_path)

    if (use_api or azure_token) and not lang:
        print("ERROR: Specify language with -l")
        sys.exit()


    out_json_path = os.path.join(out_path ,os.path.splitext(os.path.basename(audio_path))[0] + '-diarization.json')
    out_empty_otr_path = os.path.join(out_path ,os.path.splitext(os.path.basename(audio_path))[0] + '-diarization.otr')
    out_final_otr_path = os.path.join(out_path ,os.path.splitext(os.path.basename(audio_path))[0] + '-autotemplate.otr')

    #Ensure wav format input
    wav_path = audio_convert(audio_path)

    #Perform (or read) diarization
    if os.path.exists(out_json_path):
        #Load diarization dictionary
        print("Reading diarization output", out_json_path)
        with open(out_json_path, 'r') as f:
            diarization_dict_data = f.read()
            
        diarization_dict = json.loads(diarization_dict_data)
    else:
        print("Performing diarization")
        diarization_dict = do_diarization(wav_path)

        #Write intermediate JSON to file
        with open(out_json_path, 'w') as f:
            print("Dumping diarization output", out_json_path)
            f.write(json.dumps(diarization_dict))

    print("diarization_dict")
    print(diarization_dict)

    #Make empty OTR template
    speaker_turns = get_speaker_turns(diarization_dict['content'])
    
    #Write empty template to disk
    print("Dumping diarized template", out_empty_otr_path)
    speaker_turns_to_otr(speaker_turns, out_empty_otr_path)

    #Initialize transcription
    if use_api:
        asr_service = ASR_API_FLAG
        speech_config = initialize_api_config(lang)
    elif azure_token:
        asr_service = AZURE_ASR_FLAG
        speech_config = initialize_azure_config(azure_token, lang)
    else:
        asr_service = None

    if asr_service:
        #Process audio?
        complete_audio = AudioSegment.from_wav(wav_path)

        #Create temp directory to store audio chunks
        tmp_dir_path = tempfile.mkdtemp()
        
        #Transcribe speaker turns
        for t in speaker_turns:
            t['text'] = get_transcription_of_chunk(complete_audio, t['start'], t['end'], tmp_dir_path, asr_service, speech_config)

        print('after transcribe', speaker_turns)

        #Write transcribed template to disk
        print("Dumping transcribed template", out_final_otr_path)
        speaker_turns_to_otr(speaker_turns, out_final_otr_path)

        #Remove temp directory
        # shutil.rmtree(tmp_dir_path)

if __name__ == "__main__":
    main()