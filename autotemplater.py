# Create automatically diarized and transcribed oTranscribe template using pyannote and ASR API or Azure 

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

API_TRANSCRIBE_URL = "http://127.0.0.1:8010/transcribe/short"
ASR_API_FLAG = 'api'
AZURE_ASR_FLAG = 'azure'
DEFAULT_AZURE_REGION = 'westeurope'
SUPPORTED_ASR_SERVICE_TAGS = [ASR_API_FLAG, AZURE_ASR_FLAG]
SPEAKER_DELIMITER = ':'

parser = argparse.ArgumentParser(description="oTranscribe template maker")
parser.add_argument('-i', '--audio', type=str, required=True, help='Input audio path')
parser.add_argument('-l', '--lang', type=str, help='Language')
parser.add_argument('-o', '--out', type=str, help='Output directory')
parser.add_argument('-p', '--punctoken', type=str, help='PunkProse token if sending to remote API (Not implemented)') #TODO
parser.add_argument('-a', '--azuretoken', type=str, help='Azure token if sending to Azure ASR')
parser.add_argument('-r', '--azureregion', type=str, help='Azure region if sending to Azure ASR (default: westeurope)', default=DEFAULT_AZURE_REGION)
parser.add_argument('-x', '--transcribe', type=str, help='Automatic transcription service %s'%(SUPPORTED_ASR_SERVICE_TAGS))
parser.add_argument('-u', '--apiurl', type=str, help='ASR-API URL endpoint (e.g. http://127.0.0.1:8010/transcribe/short)', default=API_TRANSCRIBE_URL)
parser.add_argument('-t', '--turn', type=str, help='Turn on speaker or speech segment (default: segment)', default='segment')
parser.add_argument('-s', '--sid', action='store_true', help='Write speaker id on turns (default: False)')

def sec_to_timestamp(sec):
    ty_res = time.gmtime(sec)
    res = time.strftime("%H:%M:%S",ty_res)
    return res

def timestamp_spanner(sec):
    ty_res = time.gmtime(sec)
    res = sec_to_timestamp(sec)
    span_str = '<span class="timestamp" data-timestamp="%s">%s</span>'%(sec, res)
    return span_str

def get_speaker_turns(diarization_output, turn_on_speaker_change):
    speaker_turns = []
    current_turn = {'speaker':None, 'start':None, 'end':None}
    for s in diarization_output:
        speaker_change = not s['label'] == current_turn['speaker']

        if not turn_on_speaker_change or speaker_change:
            #close current turn (unless it's the first turn)
            if current_turn['speaker']:
                speaker_turns.append(current_turn)

            #start new turn
            current_turn = {}
            current_turn['start'] = s['segment']['start']
            current_turn['end'] = s['segment']['end']
            current_turn['speaker'] = s['label']
        else:
            current_turn['end'] = s['segment']['end']

    if current_turn:
        current_turn['end'] = s['segment']['end']
        speaker_turns.append(current_turn)
            
    return speaker_turns

def speaker_turns_to_otr(speaker_turns, output_path, write_speaker_id=False):
    otr_text = ""
    for t in speaker_turns:
        otr_text += timestamp_spanner(t['start']) + ' '
        
        if write_speaker_id and 'speaker' in t:
            otr_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        if 'text' in t:
            otr_text += t['text']
        otr_text += '<br /><br />'
        
    otr_format_dict = {'text': otr_text, "media": "", "media-time":"0.0"}
    
    with open(output_path, 'w') as f:
        f.write(json.dumps(otr_format_dict))

def speaker_turns_to_txt(speaker_turns, output_path, write_speaker_id=False):
    out_text = ""
    for t in speaker_turns:
        out_text += sec_to_timestamp(t['start']) + ' '
        
        if write_speaker_id and 'speaker' in t:
            out_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        if 'text' in t:
            out_text += t['text']
        out_text += '\n'
            
    with open(output_path, 'w') as f:
        f.write(out_text)

def do_diarization(wav_path):
    from pyannote.core import Annotation, Segment
    from pyannote.audio.features import RawAudio

    file = {'audio': wav_path}
    pipeline = torch.hub.load('pyannote/pyannote-audio', 'dia')
    diarization = pipeline(file)
    diarization_dict = diarization.for_json()

    return diarization_dict

#Converts audio to mono wav (unless it's already or there's a converted version in the same directory)
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


def initialize_azure_config(subscription_id, lang_code, region):
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

#Converts seconds to otranscribe timestamp
def timestamp_spanner(sec):
    ty_res = time.gmtime(sec)
    res = time.strftime("%H:%M:%S",ty_res)
    span_str = '<span class="timestamp" data-timestamp="%s">%s</span>'%(sec, res)
    return span_str

def initialize_api_config(lang, api_url_endpoint, scorer='default'):
    return {'lang': lang, 'scorer':scorer, 'url': api_url_endpoint}

def transcribe_with_asr_api(audio_path, config):
    url_endpoint = config['url']
    payload={'lang': config['lang']} #TODO: doesn't get the scorer in. 
    headers = {}
    
    #Send to ASR API
    audio_filename = os.path.basename(audio_path)
    
    files=[('file',(audio_filename, open(audio_path,'rb'),'audio/wav'))]
    
    try:
        response = requests.request("POST", url_endpoint, headers=headers, data=payload, files=files)
    except Exception as e:
        print("ERROR: Cannot establish connection with ASR API")
        print(e)
        return ""
    
    response_dict = response.json()

    if response.ok:
        transcript = response_dict["transcript"]
    else:
        print("Cannot read response for file", audio_filename)
        print(response_dict)
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
    
    #print("%.2f-%.2f: %s"%(start_sec, end_sec, transcript))
    return transcript

def main():
    args = parser.parse_args()

    audio_path = args.audio
    out_path = args.out
    lang = args.lang
    azure_token = args.azuretoken
    azure_region = args.azureregion
    asr_service = args.transcribe
    turn_on = args.turn
    write_speaker_id = args.sid
    asr_api_url_endpoint = args.apiurl

    if not audio_path:
        print("ERROR: Specify input audio path (-i)")
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

    if asr_service and not asr_service in SUPPORTED_ASR_SERVICE_TAGS:
        print("ERROR: ASR service %s not supported. Select from %s"%(asr_service, SUPPORTED_ASR_SERVICE_TAGS))
        sys.exit()

    if asr_service and not lang:
        print("ERROR: Specify audio language with -l")
        sys.exit()

    if asr_service==AZURE_ASR_FLAG and not azure_token:
        print("ERROR: Specify service token to use Azure transcription (-a)")
        sys.exit()

    #Check file exists
    if not os.path.exists(audio_path):
        print("ERROR: File not found", audio_path)
        sys.exit()

    if turn_on == 'speaker':
        turn_on_speaker_change = True
    else:
        turn_on_speaker_change = False
    print('Turn on speaker change:', turn_on_speaker_change)

    #Output files 
    out_json_path = os.path.join(out_path ,os.path.splitext(os.path.basename(audio_path))[0] + '-diarization.json')
    out_empty_otr_path = os.path.join(out_path ,os.path.splitext(os.path.basename(audio_path))[0] + '-diarization.otr')
    out_final_otr_path = os.path.join(out_path ,os.path.splitext(os.path.basename(audio_path))[0] + '-autotemplate.otr')
    out_txt_path = os.path.join(out_path ,os.path.splitext(os.path.basename(audio_path))[0] + '-transcript.txt')

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

    # print("diarization_dict")
    # print(diarization_dict)

    #Make empty OTR template
    speaker_turns = get_speaker_turns(diarization_dict['content'], turn_on_speaker_change)
    
    #Write empty template to disk
    print("Dumping diarized template", out_empty_otr_path)
    speaker_turns_to_otr(speaker_turns, out_empty_otr_path, write_speaker_id)

    #Initialize transcription
    if asr_service == ASR_API_FLAG:
        asr_service = ASR_API_FLAG
        speech_config = initialize_api_config(lang, asr_api_url_endpoint)
    elif asr_service == AZURE_ASR_FLAG:
        speech_config = initialize_azure_config(azure_token, lang, azure_region)
    else:
        asr_service = None

    if asr_service:
        #Read audio to memory
        complete_audio = AudioSegment.from_wav(wav_path)

        #Create temp directory to store audio chunks
        tmp_dir_path = tempfile.mkdtemp()
        
        #Transcribe speaker turns
        for t in speaker_turns:
            t['text'] = get_transcription_of_chunk(complete_audio, t['start'], t['end'], tmp_dir_path, asr_service, speech_config)
            print("%.2f-%.2f (%s): %s"%(t['start'], t['end'], t['speaker'], t['text']))

        #Write transcribed template to disk
        print("Dumping transcribed template", out_final_otr_path)
        speaker_turns_to_otr(speaker_turns, out_final_otr_path, write_speaker_id)

        print("Dumping transcribed text", out_txt_path)
        speaker_turns_to_txt(speaker_turns, out_txt_path, write_speaker_id)

        #Remove temp directory
        shutil.rmtree(tmp_dir_path)

if __name__ == "__main__":
    main()
