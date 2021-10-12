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
import random
import requests
from pydub import AudioSegment
from tqdm import tqdm

API_TRANSCRIBE_URL = "http://127.0.0.1:8010/transcribe/short"  #default running on local
ASR_API_FLAG = 'api'
AZURE_ASR_FLAG = 'azure'
DEFAULT_AZURE_REGION = 'westeurope'
SUPPORTED_ASR_SERVICE_TAGS = [ASR_API_FLAG, AZURE_ASR_FLAG]
SPEAKER_DELIMITER = ':'
SAMPLE_COUNT = 5
MAX_SEGMENT_LENGTH = 30.0
SEGMENT_AT_PAUSE_LENGTH = 5.0
USE_AZURE_SDK = True #if false, it'll use requests library (works but sometimes unstable)

parser = argparse.ArgumentParser(description="oTranscribe template maker")
parser.add_argument('-i', '--audio', type=str, required=True, help='Input audio path')
parser.add_argument('-l', '--lang', type=str, help='Transcription language')
parser.add_argument('-o', '--out', type=str, help='Output directory (default: input audio directory)')
parser.add_argument('-p', '--punctoken', type=str, help='PunkProse token if sending to remote API (Not implemented)') #TODO
parser.add_argument('-a', '--azuretoken', type=str, help='Azure token if sending to Azure ASR')
parser.add_argument('-r', '--azureregion', type=str, help='Azure region if sending to Azure ASR (default: %s)'%DEFAULT_AZURE_REGION, default=DEFAULT_AZURE_REGION)
parser.add_argument('-x', '--transcribe', type=str, help='Automatic transcription service %s'%(SUPPORTED_ASR_SERVICE_TAGS))
parser.add_argument('-u', '--apiurl', type=str, help='ASR-API URL endpoint (default: http://127.0.0.1:8010/transcribe/short)', default=API_TRANSCRIBE_URL)
parser.add_argument('-t', '--turn', type=str, help='Turn on speaker or speech segment (default: segment)', default='segment')
parser.add_argument('-s', '--sid', action='store_true', help='Write speaker id on turns (default: False)')
parser.add_argument('-v', '--skiprevision', action='store_true', help='Skip revision query (default: False)')

def sec_to_timestamp(sec) -> str:
    """Convert seconds to timestamp format"""
    ty_res = time.gmtime(sec)
    res = time.strftime("%H:%M:%S",ty_res)
    return res

def timestamp_spanner(sec) -> str:
    """Creates an XML line for timestamp from seconds in audio"""
    ty_res = time.gmtime(sec)
    res = sec_to_timestamp(sec)
    span_str = '<span class="timestamp" data-timestamp="%s">%s</span>'%(sec, res)
    return span_str

def get_speaker_turns(diarization_output, turn_on_speaker_change, max_segment_length = MAX_SEGMENT_LENGTH, segment_at_pause_length = SEGMENT_AT_PAUSE_LENGTH):
    """Makes a minimal speaker turn list from diarization output. Merges segments that belong to same speaker"""

    speaker_turns = []
    current_turn = {'speaker':None, 'start':0.0, 'end':0.0}
    for s in diarization_output:
        speaker_change = not s['label'] == current_turn['speaker']
        current_turn_length = current_turn['end'] - current_turn['start']
        pause_from_last_segment = s['segment']['start'] - current_turn['end']

        if not turn_on_speaker_change or speaker_change or current_turn_length > max_segment_length or pause_from_last_segment >= segment_at_pause_length:
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
    """Creates an OTR template from speaker turn list"""

    otr_text = ""
    for t in speaker_turns:
        if 'text' in t:
            if not t['text']:
                continue 

        otr_text += timestamp_spanner(t['start']) + ' '
        
        if write_speaker_id: #and 'speaker' in t:
            otr_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        if 'text' in t:
            otr_text += t['text']
        otr_text += '<br /><br />'
        
    otr_format_dict = {'text': otr_text, "media": "", "media-time":"0.0"}
    
    with open(output_path, 'w') as f:
        f.write(json.dumps(otr_format_dict))

def speaker_turns_to_txt(speaker_turns, output_path, write_speaker_id=False):
    """Creates an TXT file from speaker turn list"""

    out_text = ""
    for t in speaker_turns:
        if 'text' in t:
            if not t['text']:
                continue 
            
        out_text += sec_to_timestamp(t['start']) + ' '
        
        if write_speaker_id:# and 'speaker' in t:
            out_text += '(' + t['speaker'] + ')' + SPEAKER_DELIMITER + " "
        if 'text' in t:
            out_text += t['text']
        out_text += '\n'
            
    with open(output_path, 'w') as f:
        f.write(out_text)

def print_speakers_data(diarization_dict):
    """Prints number of speakers and number of segments for each of them on the screen"""

    speakers_info = {}
    for s in diarization_dict['content']:
        if s['label'] not in speakers_info:
            speakers_info[s['label']] = 1
        else:
            speakers_info[s['label']] += 1
    print("%i speakers detected"%len(speakers_info))
    for s in speakers_info:
        print("%s: %i segments"%(s, speakers_info[s]))

def do_diarization(wav_path):
    """Performs pyannote diarization on wav file and outputs its results"""

    from pyannote.core import Annotation, Segment
    from pyannote.audio.features import RawAudio

    file = {'audio': wav_path}
    pipeline = torch.hub.load('pyannote/pyannote-audio', 'dia')
    diarization = pipeline(file)
    diarization_dict = diarization.for_json()

    return diarization_dict

def audio_convert(audio_path):
    """Converts audio to mono wav (unless it's already or there's a converted version in the same directory)"""

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
        wav_path = os.path.join(os.path.dirname(audio_path), os.path.splitext(os.path.basename(audio_path))[0] + '.wav')
        if os.path.exists(wav_path):
            return audio_convert(wav_path)
        else:
            do_convert = True

    if do_convert:
        process = subprocess.call(['ffmpeg', '-loglevel', 'quiet', '-i',
                                        audio_path, '-ac', '1', wav_path])

        print("Converting audio to wav", wav_path)

        return wav_path
    else:
        print("Reading wav", audio_path)

        return audio_path


def initialize_azure_config_sdk(subscription_id, lang_code, region):
    """Returns speech_config to run azure ASR using Azure speech SDK"""
    global speechsdk
    import azure.cognitiveservices.speech as speechsdk

    speech_config = speechsdk.SpeechConfig(subscription=subscription_id, region=region)
    speech_config.speech_recognition_language=lang_code

    return speech_config

def initialize_azure_config_requests(subscription_id, lang_code, region):
    """Generates necessary info to do Azure Speech ASR using requests"""

    url = "https://" + region + ".stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1?language=" + lang_code + "&format=detailed"
    fetch_token_url = 'https://westeurope.api.cognitive.microsoft.com/sts/v1.0/issueToken'
    headers = {
        'Ocp-Apim-Subscription-Key': subscription_id
    }
    response = requests.post(fetch_token_url, headers=headers)

    token  = str(response.text)
    headers = {
          'Authorization': f'Bearer {token}',
          'Content-Type': 'audio/wave',
          'Accept': 'application/json'
        }
    return {'token':token, 'url':url, 'headers':headers}

def transcribe_with_azure_sdk(audio_path, speech_config):
    """Does recognition with Azure on give audio using Azure speech SDK"""
    audio_input = speechsdk.AudioConfig(filename=audio_path)
    speech_recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_input)

    result = speech_recognizer.recognize_once_async().get()
    return result.text

def transcribe_with_azure_requests(audio_path, speech_config):
    """Sends a Azure API recognition request for audio and returns its transcript"""
    transcript = ''
    with open(audio_path,"rb") as payload:
        response = requests.request("POST", speech_config['url'], headers=speech_config['headers'], data=payload)

        if response.status_code == 200:
            response_json = response.json()
            try:
                transcript = response_json['NBest'][0]['Display']
            except:
                pass
        else:
            print("Error processing", audio_path)
            print(response.text.encode('utf8'))

    return transcript

def initialize_api_config(lang, api_url_endpoint, scorer='default'):
    """Generates necessary info to do ASR with TWB-API"""
    return {'lang': lang, 'scorer':scorer, 'url': api_url_endpoint}

def transcribe_with_asr_api(audio_path, config):
    """Sends a ASR-API recognition request for audio and returns its transcript"""
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

def get_transcription_of_chunk(complete_audio, start_sec, end_sec, chunk_path, transcriber_func, speech_config=None):
    """Transcribes an interval of audio with start and end seconds specified using ASR service"""

    start_ms = start_sec * 1000
    end_ms = end_sec * 1000
    
    audio_segment = complete_audio[start_ms:end_ms]
    
    audio_chunk_filename = "%.2f"%start_sec + "-" + "%.2f"%end_sec + ".wav"
    audio_chunk_path = os.path.join(chunk_path, audio_chunk_filename)
    
    audio_segment.export(audio_chunk_path, format="wav")
    
    transcript = transcriber_func(audio_chunk_path, speech_config)

    #print("%.2f-%.2f: %s"%(start_sec, end_sec, transcript))
    return transcript

def dump_chunk(audio, start_sec, end_sec, chunk_path):
    """Cuts and places a chunk of audio to path (for revision)"""

    start_ms = start_sec * 1000
    end_ms = end_sec * 1000

    audio_segment = audio[int(start_ms):int(end_ms)]
    
    audio_chunk_filename = "%.2f"%start_sec + "-" + "%.2f"%end_sec + ".wav"
    audio_chunk_path = os.path.join(chunk_path, audio_chunk_filename)
    
    audio_segment.export(audio_chunk_path, format="wav")
    
    return audio_chunk_path

def main():

    #Parse args
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
    skip_revision_query = args.skiprevision

    #Input checks
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

    if asr_service and not lang:
        print("ERROR: Specify audio language with -l")
        sys.exit()

    #Determine ASR procedure to use
    if asr_service==AZURE_ASR_FLAG:
        if asr_service==AZURE_ASR_FLAG and not azure_token:
            print("ERROR: Specify service token to use Azure transcription (-a)")
            sys.exit()

        if USE_AZURE_SDK:
            transcribe_func = transcribe_with_azure_sdk
            initialize_azure_config = initialize_azure_config_sdk
        else:
            transcribe_func = transcribe_with_azure_requests
            initialize_azure_config = initialize_azure_config_requests
    elif asr_service == ASR_API_FLAG:
        transcribe_func = transcribe_with_asr_api
    else:
        print("ERROR: ASR service %s not supported. Select from %s"%(asr_service, SUPPORTED_ASR_SERVICE_TAGS))
        sys.exit()

    #Check audio file exists
    if not os.path.exists(audio_path):
        print("ERROR: File not found", audio_path)
        sys.exit()

    if turn_on == 'speaker':
        turn_on_speaker_change = True
    else:
        turn_on_speaker_change = False
    print('Turn on speaker change:', turn_on_speaker_change)

    #Output files 
    audio_id = os.path.splitext(os.path.basename(audio_path))[0]
    out_json_path = os.path.join(out_path ,audio_id + '-rawdiarization.json')
    out_empty_otr_path = os.path.join(out_path ,audio_id + '-diarization.otr')
    out_final_otr_path = os.path.join(out_path ,audio_id + '-autotemplate.otr')
    out_txt_path = os.path.join(out_path ,audio_id + '-transcript.txt')
    out_mapped_json_path = os.path.join(out_path ,audio_id + '-reviseddiarization.json')
    out_mapping_path = os.path.join(out_path ,audio_id + '-spkrevisionmap.json')

    #Ensure wav format input
    wav_path = audio_convert(audio_path)

    #Read audio to memory
    complete_audio = AudioSegment.from_wav(wav_path)

    #Perform (or read) diarization
    if os.path.exists(out_mapped_json_path):
        #Load diarization dictionary
        print("Reading revised diarization output", out_mapped_json_path)
        with open(out_mapped_json_path, 'r') as f:
            diarization_dict_data = f.read()
            
        diarization_dict = json.loads(diarization_dict_data)
        skip_revision_query = True
    elif os.path.exists(out_json_path):
        #Load diarization dictionary
        print("Reading raw diarization output", out_json_path)
        with open(out_json_path, 'r') as f:
            diarization_dict_data = f.read()
            
        diarization_dict = json.loads(diarization_dict_data)
    else:
        print("Performing diarization")
        diarization_dict = do_diarization(wav_path)

        #Write intermediate JSON to file
        with open(out_json_path, 'w') as f:
            print("Dumping raw diarization output", out_json_path)
            f.write(json.dumps(diarization_dict))

    # print("diarization_dict")
    # print(diarization_dict)

    #Print speakers data
    print_speakers_data(diarization_dict)

    do_revision = False
    if not skip_revision_query:
        #Perform speaker label revision (optional)
        perform_revision_input = input("Do you want to revise speaker labels? (y for yes) ")
        speaker_label_map_dict = {}
        
        if perform_revision_input == 'y' or perform_revision_input == 'Y':
            
            if os.path.exists(out_mapping_path):
                print("Found a mapping file with following info")
                with open(out_mapping_path, 'r') as f:
                    mapping_dict = f.read()
                
                speaker_label_map_dict = json.loads(mapping_dict)
                print(mapping_dict)
                use_savedmapping_input = input("Do you want to use it? (y for yes) ")
                if not use_savedmapping_input == 'y' and not use_savedmapping_input == 'Y':
                    do_revision = True
            else:
                do_revision = True

    if do_revision:
        #Do revision
        speaker_segments = {}
        for i, segment_info in enumerate(diarization_dict['content']):
            if segment_info['label'] not in speaker_segments:
                speaker_segments[segment_info['label']] = [i]
            else:
                speaker_segments[segment_info['label']].append(i)

        #Open directory for revision
        revision_path = "revision"
        if not os.path.exists(revision_path):
            os.makedirs(revision_path)
            
        project_revision_path = os.path.join(revision_path, audio_id)

        if not os.path.exists(project_revision_path):
            os.makedirs(project_revision_path)

        print("Revise speaker samples from path " + project_revision_path)

        for spk in speaker_segments:
            print(spk)
            spk_utt_ids = speaker_segments[spk]
            pick_no = SAMPLE_COUNT if SAMPLE_COUNT < len(spk_utt_ids) else len(spk_utt_ids)
            
            pick = random.sample(spk_utt_ids, pick_no)
            
            #Open directory for spk under revision
            spk_revision_path = os.path.join(project_revision_path, spk)
            if not os.path.exists(spk_revision_path):
                os.makedirs(spk_revision_path)
            
            #Cut and place utterances under directory
            for utt_id in pick:
                utt_path = dump_chunk(complete_audio, 
                                      float(diarization_dict['content'][utt_id]['segment']['start']), 
                                      float(diarization_dict['content'][utt_id]['segment']['end']), 
                                      spk_revision_path)
                print(utt_path)
                
            print()

        print("Please specify names for each label")
        for spk in speaker_segments:
            mapto = input(spk + " is... ")
            speaker_label_map_dict[spk] = mapto
            
        with open(out_mapping_path, 'w') as f:
            print("Dumping mapping data", out_mapping_path)
            f.write(json.dumps(speaker_label_map_dict))

        print("Revised speaker labels")

        reversed_speaker_label_map_dict = {}
        for org_label in speaker_label_map_dict:
            new_label = speaker_label_map_dict[org_label]
            if new_label in reversed_speaker_label_map_dict:
                reversed_speaker_label_map_dict[new_label].append(org_label)
            else:
                reversed_speaker_label_map_dict[new_label] = [org_label]
            
        print(reversed_speaker_label_map_dict)

        #Update diarization dict with new label set
        mapped_diarization_dict = diarization_dict.copy()
        for segment in mapped_diarization_dict['content']:
            old_label = segment['label']
            segment['label'] = speaker_label_map_dict[old_label]

        #Write intermediate JSON to file
        with open(out_mapped_json_path, 'w') as f:
            print("Dumping mapped diarization output", out_mapped_json_path)
            f.write(json.dumps(mapped_diarization_dict))

        #Remove revision path
        shutil.rmtree(project_revision_path)
    else:
        mapped_diarization_dict = diarization_dict

    #Make empty OTR template
    speaker_turns = get_speaker_turns(mapped_diarization_dict['content'], turn_on_speaker_change)

    #print(speaker_turns) #DEBUG
    
    #Write empty template to disk
    print("Dumping diarized template", out_empty_otr_path)
    speaker_turns_to_otr(speaker_turns, out_empty_otr_path, write_speaker_id)

    #Initialize transcription
    if asr_service == ASR_API_FLAG:
        print("Initializing ASR with API on %s"%asr_api_url_endpoint)
        speech_config = initialize_api_config(lang, asr_api_url_endpoint)
    elif asr_service == AZURE_ASR_FLAG:
        print("Initializing ASR with Azure")
        speech_config = initialize_azure_config(azure_token, lang, azure_region)
    else:
        print("Skipping ASR")
        asr_service = None

    if asr_service:
        #Create temp directory to store audio chunks
        tmp_dir_path = tempfile.mkdtemp()
        print("Temp dir:", tmp_dir_path) #DEBUG
        
        #Transcribe speaker turns
        for t in tqdm(speaker_turns, desc="Transcribing segments..."):
            t['text'] = get_transcription_of_chunk(complete_audio, t['start'], t['end'], tmp_dir_path, transcribe_func, speech_config)
            # print("%.2f-%.2f (%s): %s"%(t['start'], t['end'], t['speaker'], t['text']))

        #Write transcribed template to disk
        print("Dumping transcribed template", out_final_otr_path)
        speaker_turns_to_otr(speaker_turns, out_final_otr_path, write_speaker_id)

        print("Dumping transcribed text", out_txt_path)
        speaker_turns_to_txt(speaker_turns, out_txt_path, write_speaker_id)

        #Remove temp directory
        shutil.rmtree(tmp_dir_path) #DEBUG

if __name__ == "__main__":
    main()
