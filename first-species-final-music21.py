from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import uuid
from music21 import clef, note, stream, interval, meter
from PIL import Image
from music21 import environment
environment.set('musescoreDirectPNGPath', '/Applications/MuseScore 4.app/Contents/MacOS/mscore')

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://127.0.0.1:3001"}}, supports_credentials=True)

@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "http://127.0.0.1:3001")
    response.headers.add("Access-Control-Allow-Credentials", "true")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return response

@app.route('/upload', methods=['OPTIONS'])
def options_upload():
    return '', 200

UPLOAD_FOLDER = "uploads"
SONG_FOLDER = "songs"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(SONG_FOLDER, exist_ok=True)

@app.route('/upload', methods=['POST'])
def upload_photo():
    if 'photo' not in request.files:
        return jsonify({"error": "No photo uploaded"}), 400

    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({"error": "No file selected"}), 400

    filename = str(uuid.uuid4()) + os.path.splitext(photo.filename)[1]
    photo_path = os.path.join(UPLOAD_FOLDER, filename)
    photo.save(photo_path)

    song_path, sheet_path = generate_song(photo_path)
    if not song_path:
        return jsonify({"error": "Error generating song"}), 500

    return jsonify({
        "songUrl": f"http://127.0.0.1:5000/songs/{os.path.basename(song_path)}",
        "sheetMusicUrl": f"http://127.0.0.1:5000/songs/{os.path.basename(sheet_path)}"
    })

def generate_song(photo_path):
    try:
        if not os.path.exists(photo_path):
            print("🔴 File not found:", photo_path)
            return None, None

        img = Image.open(photo_path).convert("L")
        img = img.resize((10, 10))
        pixel_values = list(img.getdata())
        print("✅ Pixel Values:", pixel_values[:10])

        tonic_pitch = 60
        scale_degrees = [0, 2, 4, 5, 7, 9, 11]
        leaps_used = 0
        highest_note = tonic_pitch + max(scale_degrees)
        highest_note_placed = False

        score = stream.Score()
        top_line = stream.Part()
        bottom_line = stream.Part()
        top_line.append(meter.TimeSignature("4/4"))
        bottom_line.append(meter.TimeSignature("4/4"))

        previous_pitch = None
        second_last_pitch = None
        previous_interval = None

        for i in range(10):
            if i == 0:
                pitch = tonic_pitch
                previous_interval = "P1"
            elif i == 9:
                valid_endings = [tonic_pitch, tonic_pitch + 7]
                pitch = min(valid_endings, key=lambda p: abs(previous_pitch - p))
            else:
                valid_pitches = []
                current_scale_step = scale_degrees.index((previous_pitch - tonic_pitch) % 12)
                for step in [-1, 1, -2, 2]:
                    next_step = current_scale_step + step
                    if 0 <= next_step < len(scale_degrees):
                        candidate_pitch = tonic_pitch + scale_degrees[next_step]
                        if candidate_pitch == previous_pitch == second_last_pitch:
                            continue
                        if abs(candidate_pitch - previous_pitch) > 2 and leaps_used >= 1:
                            continue
                        if candidate_pitch == highest_note and (highest_note_placed or abs(candidate_pitch - previous_pitch) > 2):
                            continue
                        interval_obj = interval.Interval(note.Note(previous_pitch), note.Note(candidate_pitch))
                        if interval_obj.name in ["P1", "P5", "P8"] and previous_interval in ["P1", "P5", "P8"]:
                            continue
                        valid_pitches.append(candidate_pitch)
                if not valid_pitches:
                    for step in [-1, 1]:
                        next_step = current_scale_step + step
                        if 0 <= next_step < len(scale_degrees):
                            valid_pitches.append(tonic_pitch + scale_degrees[next_step])
                pitch = valid_pitches[pixel_values.pop() % len(valid_pitches)]
                interval_obj = interval.Interval(note.Note(previous_pitch), note.Note(pitch))
                previous_interval = interval_obj.name
                if abs(pitch - previous_pitch) > 2:
                    leaps_used += 1
            if pitch == highest_note:
                highest_note_placed = True
            second_last_pitch = previous_pitch
            previous_pitch = pitch
            top_line.append(note.Note(pitch, quarterLength=4))

        print("✅ Top Line Pitches:", [n.pitch.midi for n in top_line.notes])

        previous_cf_pitch = None
        repeated_static_count = 0
        static_pitch_memory = {}

        # In your generate_song function, inside the loop where bottom line notes are generated
        # In your generate_song function, inside the loop where bottom line notes are generated

        # Track the frequency of pitches in the bottom line
        bottom_pitch_counts = {}

        for i, top_note in enumerate(top_line.notes):
            top_pitch = top_note.pitch.midi
            if i == 0 or i == 9:
                cf_pitch = tonic_pitch
            else:
                valid_cf_pitches = []
                for degree in scale_degrees:
                    pitch = tonic_pitch + degree
                    if not (48 <= pitch <= 72):
                        continue
                    interval_semitones = abs(pitch - top_pitch)
                    if interval_semitones not in [0, 3, 4, 7, 8, 9]:
                        continue

                    # Prevent unison, perfect 5th, or octave
                    interval_obj = interval.Interval(note.Note(top_pitch), note.Note(pitch))
                    if interval_obj.name in ["P1", "P5", "P8"]:  # Unison, perfect 5th, or octave
                        continue

                    # Avoid the tonic in the middle of the melody
                    if tonic_pitch == pitch and 1 <= i <= 8:  # Prevent tonic from being used between notes 1 and 8
                        continue

                    # Apply repetition penalty
                    repetition_factor = bottom_pitch_counts.get(pitch, 0) / max(1, len(bottom_line.notes))
                    repetition_penalty = repetition_factor * 10  # You can adjust this penalty value
                    score_val = -repetition_penalty

                    if previous_cf_pitch is not None:
                        motion = pitch - previous_cf_pitch
                        top_motion = top_pitch - top_line.notes[i - 1].pitch.midi
                        if (motion > 0 and top_motion < 0) or (motion < 0 and top_motion > 0):
                            score_val -= 3
                        if abs(motion) <= 2:
                            score_val -= 2
                        if abs(motion) > 7:
                            score_val += 5
                        if motion == 0:
                            score_val -= 1
                            if repeated_static_count >= 2:
                                score_val += 10  # heavy penalty for too many repeats
                            if static_pitch_memory.get(pitch, 0) >= 2:
                                score_val += 5  # penalize if pitch already repeated twice

                    valid_cf_pitches.append((pitch, score_val))
                
                if valid_cf_pitches:
                    cf_pitch = min(valid_cf_pitches, key=lambda x: x[1])[0]
                else:
                    cf_pitch = tonic_pitch

            # Update the bottom_pitch_counts and check for repeated notes
            bottom_pitch_counts[cf_pitch] = bottom_pitch_counts.get(cf_pitch, 0) + 1

            if previous_cf_pitch is not None and cf_pitch == previous_cf_pitch:
                repeated_static_count += 1
                static_pitch_memory[cf_pitch] = static_pitch_memory.get(cf_pitch, 0) + 1
            else:
                repeated_static_count = 0

            bottom_line.append(note.Note(cf_pitch, quarterLength=4))
            previous_cf_pitch = cf_pitch


        print("✅ Bottom Line Pitches:", [n.pitch.midi for n in bottom_line.notes])
        score.append(top_line)
        score.append(bottom_line)
        song_filename = str(uuid.uuid4()) + ".mid"
        sheet_filename = str(uuid.uuid4()) + ".png"
        song_path = os.path.join("songs", song_filename)
        sheet_path = os.path.join("songs", sheet_filename)
        score.write("midi", fp=song_path)
        score.write("musicxml.png", fp=sheet_path)
        return song_path, sheet_path
    except Exception as e:
        print(f"🔴 Error generating first species counterpoint: {str(e)}")
        return None, None

@app.route('/songs/<filename>', methods=['GET'])
def get_song(filename):
    song_path = os.path.join(SONG_FOLDER, filename)
    if os.path.exists(song_path):
        return send_file(song_path, as_attachment=True)
    return jsonify({"error": "Song not found"}), 404

if __name__ == '__main__':
    app.run(debug=True)
