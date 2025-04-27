from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import uuid
from music21 import clef, note, stream, interval

from PIL import Image
from PIL import Image
from music21 import environment
environment.set('musescoreDirectPNGPath', '/Applications/MuseScore 4.app/Contents/MacOS/mscore')

app = Flask(__name__)

# Correct and global CORS setup
CORS(app, resources={r"/*": {"origins": "http://127.0.0.1:3001"}}, supports_credentials=True)

# Ensures headers are always added after request (even for OPTIONS)
@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "http://127.0.0.1:3001")
    response.headers.add("Access-Control-Allow-Credentials", "true")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return response

# Optional: explicitly handle OPTIONS to silence any preflight issues
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
        "songUrl": f"http://127.0.0.1:5002/songs/{os.path.basename(song_path)}",
        "sheetMusicUrl": f"http://127.0.0.1:5002/songs/{os.path.basename(sheet_path)}"
    })
def generate_song(photo_path):
    """
    Generate a tonal first species counterpoint with the top line composed note by note.
    Rules:
        - The last note of the top line can be scale degree 0 (tonic) or 5 (dominant).
        - If the top line ends on scale degree 5, the bottom line must form a P5 or P4 interval.
        - Prefer stepwise motion to the last note in the top line.
    """
    try:
        # Step 1: Load and process the image
        if not os.path.exists(photo_path):
            print("🔴 File not found:", photo_path)
            return None, None

        img = Image.open(photo_path).convert("L")
        img = img.resize((10, 10))  # Resize to 10x10 for simplicity
        pixel_values = list(img.getdata())
        print("✅ Pixel Values:", pixel_values[:10])  # Debug pixel values

        # Step 2: Define the key and intervals
        tonic_pitch = 60  # C4 MIDI pitch
        scale_degrees = [0, 2, 4, 5, 7, 9, 11]  # C major scale degrees
        leaps_used = 0
        current_direction = None  # Tracks direction of motion (up or down)

        # Top line rules
        top_line = stream.Part()
        top_line.clef = clef.TrebleClef()  # Set treble clef
        previous_pitch = None
        second_last_pitch = None

        for i in range(10):
            if i == 0:
                # Rule: NEVER BREAK - Start with the tonic
                pitch = tonic_pitch
            elif i == 9:
                # Rule: LAST NOTE OPTIONS
                # The last note can be tonic (C4) or dominant (G4).
                valid_endings = [tonic_pitch, tonic_pitch + 7]  # Scale degree 0 or 5
                if abs(previous_pitch - valid_endings[0]) <= 2:
                    # Prefer stepwise motion to the last note
                    pitch = valid_endings[0]
                else:
                    # Default to the dominant if stepwise motion is not possible
                    pitch = valid_endings[1]
            else:
                # Select the next pitch dynamically
                valid_pitches = []
                current_scale_step = scale_degrees.index((top_line[-1].pitch.midi - tonic_pitch) % 12)

                # Generate candidate pitches based on stepwise motion and leap handling
                for step in [-1, 1, -2, 2]:  # Step sizes (up or down by 1 or 2 degrees)
                    next_scale_step = current_scale_step + step
                    if 0 <= next_scale_step < len(scale_degrees):
                        candidate_pitch = tonic_pitch + scale_degrees[next_scale_step]

                        # RULE: NEVER BREAK - Avoid triple repetition
                        if candidate_pitch == previous_pitch == second_last_pitch:
                            continue

                        # RULE: AVOID BREAK - Consecutive repeated notes in the middle
                        if candidate_pitch == previous_pitch and i > 1:
                            continue

                        # RULE: DON'T BREAK TOO OFTEN - Avoid consecutive leaps in opposite directions
                        if current_direction == "up" and step < 0:
                            continue
                        if current_direction == "down" and step > 0:
                            continue

                        # RULE: DON'T BREAK TOO OFTEN - Limit leaps to a maximum of two
                        if abs(step) > 1 and leaps_used >= 2:
                            continue

                        # Add the valid candidate pitch
                        valid_pitches.append(candidate_pitch)

                # Fallback to stepwise motion if no valid pitches are found
                if not valid_pitches:
                    for step in [-1, 1]:  # Step sizes (up or down by 1 degree)
                        next_scale_step = current_scale_step + step
                        if 0 <= next_scale_step < len(scale_degrees):
                            valid_pitches.append(tonic_pitch + scale_degrees[next_scale_step])

                # Select the next pitch based on pixel values
                pitch = valid_pitches[pixel_values.pop() % len(valid_pitches)]

                # Update direction and leap tracking
                if abs(pitch - previous_pitch) > 2:
                    leaps_used += 1
                    current_direction = "up" if pitch > previous_pitch else "down"
                else:
                    current_direction = None

            # Append the pitch to the top line
            second_last_pitch = previous_pitch
            previous_pitch = pitch
            top_line.append(note.Note(pitch))

        print("✅ Top Line Pitches:", [n.pitch.midi for n in top_line.notes])

        # Step 3: Compose the bottom line (cantus firmus)
        cantus_firmus = stream.Part()
        cantus_firmus.clef = clef.TrebleClef()  # Set treble clef
        for i, top_note in enumerate(top_line.notes):
            top_pitch = top_note.pitch.midi

            if i == 0:
                cf_pitch = tonic_pitch  # Start with the tonic in the bottom line
            elif i == 9:
                # Rule: ENDING INTERVALS
                # If the top line ends on scale degree 0, the bottom line must also end on 0.
                # If the top line ends on scale degree 5, the bottom line must form a P5 or P4.
                if top_pitch == tonic_pitch:
                    cf_pitch = tonic_pitch  # Bottom line ends on tonic
                elif top_pitch == tonic_pitch + 7:
                    cf_pitch = tonic_pitch if pixel_values.pop() % 2 == 0 else tonic_pitch + 12  # P5 or P4
            else:
                # Generate harmonic consonances (P1, m3, M3, P5, M6, P8)
                valid_intervals = [0, 3, 4, 7, 9, 12]
                cf_pitch = top_pitch - valid_intervals[pixel_values.pop() % len(valid_intervals)]

            cantus_firmus.append(note.Note(cf_pitch))

        # Step 4: Create the music21 score
        score = stream.Score([top_line, cantus_firmus])

        # Step 5: Save the score
        if not os.path.exists(SONG_FOLDER):
            os.makedirs(SONG_FOLDER)

        song_filename = str(uuid.uuid4()) + ".mid"
        song_path = os.path.join(SONG_FOLDER, song_filename)
        score.write("midi", fp=song_path)

        sheet_filename = str(uuid.uuid4()) + ".png"
        sheet_path = os.path.join(SONG_FOLDER, sheet_filename)
        score.write("musicxml.png", fp=sheet_path)

        print("✅ Song generated successfully:", song_path, sheet_path)
        return song_path, sheet_path

    except Exception as e:
        print(f"🔴 Error generating tonal first species counterpoint: {str(e)}")
        return None, None
    
@app.route('/songs/<filename>', methods=['GET'])
def get_song(filename):
    song_path = os.path.join(SONG_FOLDER, filename)
    if os.path.exists(song_path):
        return send_file(song_path, as_attachment=True)
    return jsonify({"error": "Song not found"}), 404

if __name__ == '__main__':
    app.run(debug=True)