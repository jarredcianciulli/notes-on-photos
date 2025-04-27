from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import uuid
from music21 import clef, note, stream, interval, meter
from PIL import Image
from music21 import environment

# Disable automatic rendering by clearing MuseScore paths
environment.set('musicxmlPath', '')
environment.set('musescoreDirectPNGPath', '')

app = Flask(__name__)

# Allow only your Render backend and your S3 frontend URL
CORS(app, resources={r"/upload": {"origins": [
    "http://notes-on-photos.s3-website.us-east-2.amazonaws.com",  # Your frontend S3 URL
    "https://notes-on-photos-2.onrender.com"  # Replace with your Render backend URL
]}})

@app.after_request
def after_request(response):
    return response

@app.route('/upload', methods=['OPTIONS'])
def options_upload():
    return '', 200

app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB limit

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

    note_data = generate_song(photo_path)
    if not note_data:
        return jsonify({"error": "Error generating song"}), 500

    return jsonify({
        "noteData": note_data
    })

def generate_song(photo_path):
    try:
        if not os.path.exists(photo_path):
            print("🔴 File not found:", photo_path)
            return None

        img = Image.open(photo_path).convert("L")
        img = img.resize((10, 10))
        pixel_values = list(img.getdata())
        print("✅ Pixel Values:", pixel_values[:10])

        tonic_pitch = 60  # Middle C
        scale_degrees = [0, 2, 4, 5, 7, 9, 11]  # Major scale intervals (upward)
        lower_scale_degrees = [-12, -10, -8, -7, -5, -3, -1]  # Descending intervals for downward motion

        score = stream.Score()
        top_line = stream.Part()
        bottom_line = stream.Part()
        top_line.append(meter.TimeSignature("4/4"))
        bottom_line.append(meter.TimeSignature("4/4"))

        # Generate the top line
        previous_pitch = None
        for i in range(10):
            if i == 0:
                pitch = tonic_pitch
            elif i == 9:
                pitch = tonic_pitch  # End with tonic
            else:
                valid_pitches = [tonic_pitch + degree for degree in scale_degrees]
                pitch = valid_pitches[pixel_values.pop() % len(valid_pitches)]

            top_line.append(note.Note(pitch, quarterLength=4))
            previous_pitch = pitch

        print("✅ Top Line Pitches:", [n.pitch.midi for n in top_line.notes])

        # Generate the bottom line
        previous_cf_pitch = None
        bottom_pitch_counts = {}  # Track how many times each note is used
        last_bottom_notes = []    # Track the last few notes to prevent consecutive repetition
        consecutive_repeated_notes = []  # Track notes that were repeated consecutively
        max_consecutive_repeats = 2
        max_note_usage = 3
        last_leap_direction = None  # Track the direction of the last leap

        for i, top_note in enumerate(top_line.notes):
            top_pitch = top_note.pitch.midi

            # Rules for the first and last note
            if i == 0 or i == 9:
                cf_pitch = tonic_pitch
                if i == 9:
                    cf_pitch = tonic_pitch - 12  # Favor ending on the lower tonic (octave below)
            else:
                valid_cf_pitches = []
                for degree in scale_degrees + lower_scale_degrees:  # Include descending intervals
                    candidate_pitch = tonic_pitch + degree

                    # Prevent voice crossing
                    if candidate_pitch >= top_pitch:
                        continue

                    # Prevent going below B1 (MIDI 35)
                    if candidate_pitch < 35:
                        continue

                    # Prevent notes that were repeated consecutively earlier
                    if candidate_pitch in consecutive_repeated_notes:
                        continue

                    # Enforce no more than 2 consecutive repetitions
                    if len(last_bottom_notes) >= max_consecutive_repeats and all(
                        note == candidate_pitch for note in last_bottom_notes[-max_consecutive_repeats:]
                    ):
                        # Add to repeated notes list if it's repeated consecutively
                        consecutive_repeated_notes.append(candidate_pitch)
                        continue

                    # Enforce no more than 1 note played 3 times in the entire bottom line
                    if bottom_pitch_counts.get(candidate_pitch, 0) >= max_note_usage:
                        continue

                    # Enforce leaps no larger than a 6th
                    if previous_cf_pitch and abs(candidate_pitch - previous_cf_pitch) > 9:  # 9 semitones = M6
                        continue

                    # Ensure second note is stepwise or the same as the first note
                    if i == 1 and previous_cf_pitch and abs(candidate_pitch - previous_cf_pitch) > 2:
                        continue

                    # Ensure second-to-last note is stepwise or the same as the last note
                    if i == 8 and abs(candidate_pitch - top_line.notes[9].pitch.midi) > 2:
                        continue

                    # Calculate consonance with the top pitch
                    interval_obj = interval.Interval(note.Note(candidate_pitch), note.Note(top_pitch))
                    interval_name = interval_obj.name
                    if interval_name not in ["P1", "m3", "M3", "P5", "m6", "M6", "P8"]:
                        continue  # Skip dissonant intervals (e.g., P4)

                    # Favor stepwise downward motion
                    stepwise_bonus = -10 if previous_cf_pitch and candidate_pitch == previous_cf_pitch - 1 else 0

                    # Penalize same note for second and second-to-last positions
                    if (i == 1 or i == 8) and candidate_pitch == previous_cf_pitch:
                        stepwise_bonus += 5  # Slight penalty for the same pitch

                    # Handle leaps (interval > 2 semitones)
                    if previous_cf_pitch and abs(candidate_pitch - previous_cf_pitch) > 2:
                        leap_direction = "up" if candidate_pitch > previous_cf_pitch else "down"
                        if last_leap_direction and leap_direction == last_leap_direction:
                            continue  # Skip if the leap doesn't resolve in the opposite direction
                        last_leap_direction = leap_direction
                        stepwise_bonus += 5  # Penalize leaps slightly to favor stepwise motion

                    # Scoring system to prioritize valid pitches
                    valid_cf_pitches.append((candidate_pitch, stepwise_bonus))

                # Choose the best candidate pitch based on scoring
                if valid_cf_pitches:
                    cf_pitch = min(valid_cf_pitches, key=lambda x: x[1])[0]
                else:
                    cf_pitch = tonic_pitch  # Fallback to tonic if no valid pitch is found

            # Add the selected pitch to the bottom line
            bottom_line.append(note.Note(cf_pitch, quarterLength=4))

            # Update tracking variables
            bottom_pitch_counts[cf_pitch] = bottom_pitch_counts.get(cf_pitch, 0) + 1
            last_bottom_notes.append(cf_pitch)
            if len(last_bottom_notes) > max_consecutive_repeats:
                last_bottom_notes.pop(0)

            previous_cf_pitch = cf_pitch

        print("✅ Bottom Line Pitches:", [n.pitch.midi for n in bottom_line.notes])

        # Combine the parts into the score
        score.append(top_line)
        score.append(bottom_line)

        # Prepare note data for JSON response
        note_data = {"topLine": [], "bottomLine": []}
        for tn, bn in zip(top_line.notes, bottom_line.notes):
            note_data["topLine"].append({
                "pitch": tn.pitch.midi,
                "note": tn.nameWithOctave,
                "duration": tn.quarterLength
            })
            note_data["bottomLine"].append({
                "pitch": bn.pitch.midi,
                "note": bn.nameWithOctave,
                "duration": bn.quarterLength,
                "interval": interval.Interval(note.Note(bn.pitch.midi), note.Note(tn.pitch.midi)).name
            })

        return note_data

    except Exception as e:
        print(f"🔴 Error generating song: {str(e)}")
        return None

if __name__ == '__main__':
    app.run(debug=False, port=5002)
