from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import uuid
from music21 import clef, note, stream, interval, meter
from PIL import Image
from music21 import environment
environment.set('musescoreDirectPNGPath', '/Applications/MuseScore 4.app/Contents/MacOS/mscore')

app = Flask(__name__)
CORS(app)

@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
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

    song_path, sheet_path, note_data = generate_song(photo_path)
    if not song_path:
        return jsonify({"error": "Error generating song"}), 500

    return jsonify({
        "songUrl": f"http://127.0.0.1:5000/songs/{os.path.basename(song_path)}",
        "sheetMusicUrl": f"http://127.0.0.1:5000/songs/{os.path.basename(sheet_path)}",
        "noteData": note_data
    })

def generate_song(photo_path):
    try:
        if not os.path.exists(photo_path):
            print("🔴 File not found:", photo_path)
            return None, None, None

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
        previous_cf_pitch = None
        second_last_pitch = None
        previous_interval = None
        last_bottom_notes = []
        bottom_pitch_counts = {}
        same_interval_streak = 0
        max_consecutive_repeats = 2
        max_note_usage = 3

        for i in range(10):
            # Generate the top line note
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
                        valid_pitches.append(candidate_pitch)

                pitch = valid_pitches[pixel_values.pop() % len(valid_pitches)]
            
            top_line.append(note.Note(pitch, quarterLength=4))
            previous_pitch = pitch

            # Generate the bottom line note
            top_pitch = pitch
            valid_cf_pitches = []
            for degree in scale_degrees:
                candidate_pitch = tonic_pitch + degree

                # Enforce lower bound (allow B1 and above)
                if candidate_pitch < 35:
                    continue

                # Prevent voice crossing
                if candidate_pitch >= top_pitch:
                    continue

                # Prevent more than 2 consecutive repetitions
                if len(last_bottom_notes) >= max_consecutive_repeats and all(n == candidate_pitch for n in last_bottom_notes[-max_consecutive_repeats:]):
                    continue

                # Prevent more than 3 total repetitions of the same note
                if bottom_pitch_counts.get(candidate_pitch, 0) >= max_note_usage:
                    continue

                # Skip m2 and M2 intervals
                interval_semitones = abs(candidate_pitch - top_pitch)
                if interval_semitones in [1, 2]:
                    continue

                # Allow only consonant intervals
                if interval_semitones not in [0, 3, 4, 7, 8, 9]:
                    continue

                # Score valid pitches
                motion = candidate_pitch - previous_cf_pitch if previous_cf_pitch is not None else None
                top_motion = top_pitch - top_line.notes[i - 1].pitch.midi if i > 0 else None
                contrary_motion_bonus = 0
                if motion is not None and top_motion is not None:
                    if (motion > 0 and top_motion < 0) or (motion < 0 and top_motion > 0):
                        contrary_motion_bonus = -5  # Strong bonus for contrary motion
                    elif motion * top_motion > 0:
                        contrary_motion_bonus = 2  # Slight penalty for parallel motion

                repetition_factor = bottom_pitch_counts.get(candidate_pitch, 0) / max(1, len(bottom_line.notes))
                repetition_penalty = repetition_factor * 10
                score_val = -repetition_penalty + contrary_motion_bonus

                valid_cf_pitches.append((candidate_pitch, score_val))

            # Log options and their scores
            print(f"🎯 Top Note: {top_pitch}")
            print(f"✅ Bottom Options: {[(p, s) for p, s in valid_cf_pitches]}")
            
            if valid_cf_pitches:
                cf_pitch = min(valid_cf_pitches, key=lambda x: x[1])[0]
            else:
                cf_pitch = tonic_pitch  # Fallback to tonic if no valid pitch is found

            # Add the selected pitch to the bottom line
            bottom_line.append(note.Note(cf_pitch, quarterLength=4))
            print(f"🎵 Selected Bottom Note: {cf_pitch}\n")

            # Update tracking variables
            bottom_pitch_counts[cf_pitch] = bottom_pitch_counts.get(cf_pitch, 0) + 1
            last_bottom_notes.append(cf_pitch)
            if len(last_bottom_notes) > max_consecutive_repeats:
                last_bottom_notes.pop(0)
            previous_cf_pitch = cf_pitch

        # Combine the parts into the score
        score.append(top_line)
        score.append(bottom_line)

        # Save the generated song and sheet music
        song_filename = str(uuid.uuid4()) + ".mid"
        sheet_filename = str(uuid.uuid4()) + ".png"
        song_path = os.path.join("songs", song_filename)
        sheet_path = os.path.join("songs", sheet_filename)
        score.write("midi", fp=song_path)
        score.write("musicxml.png", fp=sheet_path)

        return song_path, sheet_path, {
            "topLine": [{"pitch": n.pitch.midi, "note": n.nameWithOctave} for n in top_line.notes],
            "bottomLine": [{"pitch": n.pitch.midi, "note": n.nameWithOctave} for n in bottom_line.notes],
        }

    except Exception as e:
        print(f"🔴 Error generating first species counterpoint: {str(e)}")
        return None, None, None

@app.route('/songs/<filename>', methods=['GET'])
def get_song(filename):
    song_path = os.path.join(SONG_FOLDER, filename)
    if os.path.exists(song_path):
        return send_file(song_path, as_attachment=True)
    return jsonify({"error": "Song not found"}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5002)