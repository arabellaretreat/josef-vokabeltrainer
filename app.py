from flask import Flask, render_template, jsonify, request, Response
import json, os, uuid, random, base64, socket
from datetime import datetime, timedelta

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get('DATA_DIR', os.path.join(BASE_DIR, 'data'))
VOCAB_FILE  = os.path.join(DATA_DIR, 'vokabeln.json')
TESTS_FILE  = os.path.join(DATA_DIR, 'tests.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')

# ── helpers ────────────────────────────────────────────────────────────────
def ensure_files():
    os.makedirs(DATA_DIR, exist_ok=True)
    defaults = {
        VOCAB_FILE:    {'vocabulary': []},
        TESTS_FILE:    {'tests': []},
        SETTINGS_FILE: {'api_key': '', 'student_name': 'Josef'},
    }
    for path, default in defaults.items():
        if not os.path.exists(path):
            _save(path, default)

def _load(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def _save(filepath, data):
    tmp = filepath + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, filepath)          # atomic write — no partial saves

def grade(pct):
    if pct >= 90: return (1, 'Sehr gut',        '⭐')
    if pct >= 75: return (2, 'Gut',             '😊')
    if pct >= 60: return (3, 'Befriedigend',    '👍')
    if pct >= 50: return (4, 'Genügend',        '😐')
    return              (5, 'Nicht genügend',   '😔')

# ── routes: main ──────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ── routes: settings ──────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(_load(SETTINGS_FILE))

@app.route('/api/settings', methods=['PUT'])
def save_settings():
    data = _load(SETTINGS_FILE)
    data.update(request.json)
    _save(SETTINGS_FILE, data)
    return jsonify(data)

# ── routes: vocabulary ────────────────────────────────────────────────────
@app.route('/api/vocabulary', methods=['GET'])
def get_vocabulary():
    return jsonify(_load(VOCAB_FILE)['vocabulary'])

@app.route('/api/vocabulary', methods=['POST'])
def add_word():
    data = _load(VOCAB_FILE)
    w = request.json
    w.update(id=str(uuid.uuid4()), added_date=datetime.now().isoformat(),
             correct_count=0, wrong_count=0, streak=0, last_practiced=None)
    data['vocabulary'].append(w)
    _save(VOCAB_FILE, data)
    return jsonify(w), 201

@app.route('/api/vocabulary/<wid>', methods=['PUT'])
def update_word(wid):
    data = _load(VOCAB_FILE)
    for i, w in enumerate(data['vocabulary']):
        if w['id'] == wid:
            data['vocabulary'][i] = {**w, **request.json, 'id': wid}
            _save(VOCAB_FILE, data)
            return jsonify(data['vocabulary'][i])
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/vocabulary/<wid>', methods=['DELETE'])
def delete_word(wid):
    data = _load(VOCAB_FILE)
    data['vocabulary'] = [w for w in data['vocabulary'] if w['id'] != wid]
    _save(VOCAB_FILE, data)
    return jsonify({'ok': True})

# ── routes: import ────────────────────────────────────────────────────────
@app.route('/api/import', methods=['POST'])
def import_vocabulary():
    data   = _load(VOCAB_FILE)
    words  = request.json.get('words', [])
    added  = 0
    skipped = 0
    existing_pairs = {
        (w['deutsch'].strip().lower(), w['italienisch'].strip().lower())
        for w in data['vocabulary']
    }
    for word in words:
        de = (word.get('deutsch') or '').strip()
        it = (word.get('italienisch') or '').strip()
        if not de or not it:
            continue
        pair = (de.lower(), it.lower())
        if pair in existing_pairs:
            skipped += 1
            continue
        existing_pairs.add(pair)
        word.update(id=str(uuid.uuid4()), added_date=datetime.now().isoformat(),
                    deutsch=de, italienisch=it,
                    correct_count=0, wrong_count=0, streak=0, last_practiced=None)
        data['vocabulary'].append(word)
        added += 1
    _save(VOCAB_FILE, data)
    return jsonify({'added': added, 'skipped': skipped, 'total': len(data['vocabulary'])})

# ── routes: OCR from image ────────────────────────────────────────────────
@app.route('/api/ocr', methods=['POST'])
def ocr_image():
    settings = _load(SETTINGS_FILE)
    api_key  = settings.get('api_key', '').strip()

    payload = request.json
    image_b64   = payload.get('image_b64', '')
    media_type  = payload.get('media_type', 'image/jpeg')
    prompt_hint = payload.get('hint', '')   # optional: e.g. "Deutsch links, Italienisch rechts"

    if not image_b64:
        return jsonify({'error': 'Kein Bild übermittelt'}), 400

    if not api_key:
        return jsonify({'error': 'Kein Anthropic API-Key gesetzt. Bitte unter Einstellungen eintragen.'}), 400

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=1024,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': media_type,
                            'data': image_b64,
                        },
                    },
                    {
                        'type': 'text',
                        'text': (
                            'Extrahiere alle Vokabeln aus diesem Bild. '
                            'Gib AUSSCHLIESSLICH eine JSON-Liste zurück im Format: '
                            '[{"deutsch": "...", "italienisch": "..."}, ...]. '
                            'Wenn die Sprachen nicht eindeutig erkennbar sind, nimm an: '
                            'linke Spalte = Deutsch, rechte Spalte = Italienisch. '
                            'Keine Erklärungen, nur das JSON-Array. '
                            + (f'Hinweis: {prompt_hint}' if prompt_hint else '')
                        ),
                    },
                ],
            }],
        )
        raw = msg.content[0].text.strip()
        # Extract JSON array from response
        start = raw.find('[')
        end   = raw.rfind(']') + 1
        if start == -1 or end == 0:
            return jsonify({'error': 'Keine Vokabeln gefunden', 'raw': raw}), 422
        pairs = json.loads(raw[start:end])
        return jsonify({'pairs': pairs, 'count': len(pairs)})

    except ImportError:
        return jsonify({'error': 'Anthropic-Bibliothek nicht installiert. Bitte install.bat erneut ausführen.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── routes: test ──────────────────────────────────────────────────────────
@app.route('/api/test/generate', methods=['POST'])
def generate_test():
    vocab = _load(VOCAB_FILE)['vocabulary']
    if len(vocab) < 4:
        return jsonify({'error': 'Mindestens 4 Vokabeln benötigt'}), 400

    body      = request.json or {}
    count     = body.get('count', 20)
    direction = body.get('direction', 'de_it')
    mode      = body.get('mode', 'multiple_choice')
    category  = body.get('category', '')       # '' = all categories

    if category:
        vocab = [w for w in vocab if w.get('category', '') == category]
        if len(vocab) < 4:
            return jsonify({'error': f'Kategorie "{category}" hat weniger als 4 Vokabeln'}), 400

    count = min(count, len(vocab))

    def priority(w):
        lp = w.get('last_practiced')
        if not lp:
            return 0
        days = (datetime.now() - datetime.fromisoformat(lp)).days
        total = w['correct_count'] + w['wrong_count']
        acc   = w['correct_count'] / total if total else 0
        return acc - days * 0.05

    sorted_v  = sorted(vocab, key=priority)
    n_prio    = int(count * 0.7)
    selected  = sorted_v[:n_prio]
    rest      = [w for w in vocab if w not in selected]
    if rest:
        selected += random.sample(rest, min(count - len(selected), len(rest)))
    random.shuffle(selected)

    questions = []
    for word in selected:
        q = word['deutsch']    if direction == 'de_it' else word['italienisch']
        a = word['italienisch'] if direction == 'de_it' else word['deutsch']
        if mode == 'multiple_choice':
            others  = [w for w in vocab if w['id'] != word['id']]
            wrongs  = random.sample(others, min(3, len(others)))
            choices = [w['italienisch'] if direction == 'de_it' else w['deutsch'] for w in wrongs]
            choices.append(a)
            random.shuffle(choices)
        else:
            choices = []
        questions.append({
            'word_id': word['id'],
            'question': q,
            'correct_answer': a,
            'choices': choices,
            'mode': mode,
        })

    return jsonify({'questions': questions, 'direction': direction})

@app.route('/api/test/submit', methods=['POST'])
def submit_test():
    body    = request.json
    results = body.get('results', [])
    direction = body.get('direction', 'de_it')

    vocab_data = _load(VOCAB_FILE)
    tests_data = _load(TESTS_FILE)

    correct_cnt = sum(1 for r in results if r['correct'])
    total       = len(results)
    pct         = round(correct_cnt / total * 100) if total else 0
    gnum, gtxt, gemoji = grade(pct)

    # update per-word stats
    by_id = {w['id']: w for w in vocab_data['vocabulary']}
    for r in results:
        w = by_id.get(r['word_id'])
        if not w:
            continue
        if r['correct']:
            w['correct_count'] = w.get('correct_count', 0) + 1
            w['streak']        = w.get('streak', 0) + 1
        else:
            w['wrong_count'] = w.get('wrong_count', 0) + 1
            w['streak']      = 0
        w['last_practiced'] = datetime.now().isoformat()

    _save(VOCAB_FILE, vocab_data)

    record = dict(
        id=str(uuid.uuid4()),
        date=datetime.now().isoformat(),
        direction=direction,
        total=total,
        correct=correct_cnt,
        percentage=pct,
        grade=gnum,
        grade_text=gtxt,
        grade_emoji=gemoji,
        results=results,
    )
    tests_data['tests'].append(record)
    _save(TESTS_FILE, tests_data)

    return jsonify({**record, 'wrong_words': [r for r in results if not r['correct']]})

# ── routes: practice feedback ─────────────────────────────────────────────
@app.route('/api/practice/update', methods=['POST'])
def practice_update():
    body = request.json
    data = _load(VOCAB_FILE)
    for w in data['vocabulary']:
        if w['id'] == body['word_id']:
            if body['correct']:
                w['correct_count'] = w.get('correct_count', 0) + 1
                w['streak']        = w.get('streak', 0) + 1
            else:
                w['wrong_count'] = w.get('wrong_count', 0) + 1
                w['streak']      = 0
            w['last_practiced'] = datetime.now().isoformat()
            break
    _save(VOCAB_FILE, data)
    return jsonify({'ok': True})

# ── routes: stats ─────────────────────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    vocab  = _load(VOCAB_FILE)['vocabulary']
    tests  = _load(TESTS_FILE)['tests']

    total    = len(vocab)
    mastered = sum(1 for w in vocab if w.get('streak', 0) >= 3)
    learning = sum(1 for w in vocab if 0 < w.get('streak', 0) < 3)
    new_w    = sum(1 for w in vocab if not w.get('correct_count') and not w.get('wrong_count'))

    last_test = tests[-1] if tests else None
    next_due  = None
    if last_test:
        next_due = (datetime.fromisoformat(last_test['date']) + timedelta(days=7)).isoformat()

    recent = tests[-5:] if tests else []
    avg_g  = round(sum(t['grade'] for t in recent) / len(recent), 1) if recent else None

    return jsonify(dict(
        total_words=total, mastered=mastered, learning=learning, new_words=new_w,
        last_test=last_test, next_test_due=next_due,
        avg_grade=avg_g, total_tests=len(tests),
    ))

@app.route('/api/tests', methods=['GET'])
def get_tests():
    return jsonify(_load(TESTS_FILE)['tests'])

# ── routes: categories ────────────────────────────────────────────────────
@app.route('/api/categories', methods=['GET'])
def get_categories():
    vocab = _load(VOCAB_FILE)['vocabulary']
    cats  = sorted({w.get('category', 'Allgemein') for w in vocab if w.get('category')})
    counts = {c: sum(1 for w in vocab if w.get('category') == c) for c in cats}
    return jsonify([{'name': c, 'count': counts[c]} for c in cats])

# ── routes: translate ─────────────────────────────────────────────────────
@app.route('/api/translate', methods=['POST'])
def translate():
    body     = request.json or {}
    text     = body.get('text', '').strip()
    direction = body.get('direction', 'auto')   # 'de_it', 'it_de', or 'auto'

    if not text:
        return jsonify({'error': 'Kein Text eingegeben'}), 400

    # 1. Try vocabulary lookup first (fast, no API needed)
    vocab = _load(VOCAB_FILE)['vocabulary']
    text_lower = text.lower()
    matches = []
    for w in vocab:
        if direction in ('de_it', 'auto') and w['deutsch'].lower() == text_lower:
            matches.append({'source': w['deutsch'], 'translation': w['italienisch'],
                            'direction': 'de_it', 'source_label': 'aus Vokabeln'})
        if direction in ('it_de', 'auto') and w['italienisch'].lower() == text_lower:
            matches.append({'source': w['italienisch'], 'translation': w['deutsch'],
                            'direction': 'it_de', 'source_label': 'aus Vokabeln'})
    if matches:
        return jsonify({'results': matches, 'source': 'vocabulary'})

    # 2. Fall back to Anthropic API
    settings = _load(SETTINGS_FILE)
    api_key  = settings.get('api_key', '').strip()
    if not api_key:
        return jsonify({'error': 'Wort nicht in Vokabeln. Bitte API-Key in Einstellungen eintragen für KI-Übersetzung.'}), 404

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        if direction == 'de_it':
            prompt = f'Übersetze diesen deutschen Text ins Italienische. Antworte NUR mit der Übersetzung, ohne Erklärung:\n{text}'
        elif direction == 'it_de':
            prompt = f'Traduci questo testo italiano in tedesco. Rispondi SOLO con la traduzione, senza spiegazioni:\n{text}'
        else:
            prompt = (f'Erkenne die Sprache (Deutsch oder Italienisch) und übersetze in die jeweils andere Sprache. '
                      f'Antworte im Format: "SPRACHE: [Sprache] | ÜBERSETZUNG: [Übersetzung]"\nText: {text}')

        msg = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=256,
            messages=[{'role': 'user', 'content': prompt}]
        )
        result = msg.content[0].text.strip()

        if direction == 'auto' and 'ÜBERSETZUNG:' in result:
            parts   = result.split('|')
            lang    = parts[0].replace('SPRACHE:', '').strip() if len(parts) > 1 else ''
            transl  = parts[-1].replace('ÜBERSETZUNG:', '').strip()
            det_dir = 'de_it' if 'deutsch' in lang.lower() else 'it_de'
        else:
            transl  = result
            det_dir = direction

        return jsonify({'results': [{'source': text, 'translation': transl,
                                     'direction': det_dir, 'source_label': 'KI-Übersetzung'}],
                        'source': 'ai'})
    except ImportError:
        return jsonify({'error': 'Anthropic-Bibliothek nicht installiert.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── routes: homework ──────────────────────────────────────────────────────
@app.route('/api/homework/upload', methods=['POST'])
def homework_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei hochgeladen'}), 400
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Keine Datei ausgewählt'}), 400

    fname = file.filename.lower()
    try:
        if fname.endswith('.docx'):
            try:
                import docx
            except ImportError:
                return jsonify({'error': 'python-docx nicht installiert. Bitte install.bat erneut ausführen.'}), 500
            from io import BytesIO
            doc = docx.Document(BytesIO(file.read()))
            lines = [p.text for p in doc.paragraphs if p.text.strip()]
            content = '\n'.join(lines)

        elif fname.endswith('.pdf'):
            try:
                import pdfplumber
            except ImportError:
                return jsonify({'error': 'pdfplumber nicht installiert. Bitte install.bat erneut ausführen.'}), 500
            from io import BytesIO
            with pdfplumber.open(BytesIO(file.read())) as pdf:
                pages = [p.extract_text() or '' for p in pdf.pages]
            content = '\n\n'.join(p for p in pages if p.strip())

        else:
            return jsonify({'error': 'Nur .docx und .pdf Dateien werden unterstützt'}), 400

        if not content.strip():
            return jsonify({'error': 'Kein Text im Dokument gefunden'}), 422

        return jsonify({'content': content, 'filename': file.filename})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── helper: local IP ──────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

# ── start ─────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    ensure_files()
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'reconfigure') else None

    port     = int(os.environ.get('PORT', 5000))
    is_cloud = bool(os.environ.get('PORT') or os.environ.get('RENDER') or os.environ.get('RAILWAY_ENVIRONMENT'))

    if not is_cloud:
        import threading, webbrowser, time
        local_ip = get_local_ip()

        def _open():
            time.sleep(1.2)
            webbrowser.open(f'http://localhost:{port}')
        threading.Thread(target=_open, daemon=True).start()

        print('=' * 55)
        print("  Josef's Vokabeltrainer DE <> IT")
        print('=' * 55)
        print(f'  PC:       http://localhost:{port}')
        print(f'  iPhone:   http://{local_ip}:{port}')
        print('  (Fenster offen lassen!)')
        print('=' * 55)

    app.run(debug=False, port=port, host='0.0.0.0', use_reloader=False)
