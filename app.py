from flask import Flask, render_template, jsonify, request, Response
import json, os, uuid, random, base64, socket, shutil
from datetime import datetime, timedelta

app = Flask(__name__)
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.environ.get('DATA_DIR', os.path.join(BASE_DIR, 'data'))
SEED_DIR  = os.path.join(BASE_DIR, 'data_seed')

# ── JSON file paths (local fallback) ──────────────────────────────────────────
VOCAB_FILE    = os.path.join(DATA_DIR, 'vokabeln.json')
TESTS_FILE    = os.path.join(DATA_DIR, 'tests.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')

# ── Supabase config ────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

# ══════════════════════════════════════════════════════════════════════════════
# DATA STORE  –  abstraction over JSON files (local) or Supabase (cloud)
# ══════════════════════════════════════════════════════════════════════════════
class DataStore:
    def __init__(self):
        self._sb = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                from supabase import create_client
                self._sb = create_client(SUPABASE_URL, SUPABASE_KEY)
            except ImportError:
                pass   # fall back to JSON

    @property
    def cloud(self):
        return self._sb is not None

    # ── helpers (local JSON) ───────────────────────────────────────────────
    def _jload(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _jsave(self, path, data):
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _ensure_local(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        defaults = {
            VOCAB_FILE:    {'vocabulary': []},
            TESTS_FILE:    {'tests': []},
            SETTINGS_FILE: {'api_key': '', 'student_name': 'Josef'},
        }
        for path, default in defaults.items():
            if not os.path.exists(path):
                seed = os.path.join(SEED_DIR, os.path.basename(path))
                if os.path.exists(seed):
                    shutil.copy2(seed, path)
                else:
                    self._jsave(path, default)

    # ── vocabulary ─────────────────────────────────────────────────────────
    def get_vocabulary(self):
        if self.cloud:
            return self._sb.table('vocabulary').select('*').order('added_date').execute().data
        return self._jload(VOCAB_FILE)['vocabulary']

    def add_word(self, word):
        if self.cloud:
            self._sb.table('vocabulary').insert(word).execute()
        else:
            data = self._jload(VOCAB_FILE)
            data['vocabulary'].append(word)
            self._jsave(VOCAB_FILE, data)

    def update_word(self, wid, changes):
        if self.cloud:
            self._sb.table('vocabulary').update(changes).eq('id', wid).execute()
            r = self._sb.table('vocabulary').select('*').eq('id', wid).execute()
            return r.data[0] if r.data else None
        else:
            data = self._jload(VOCAB_FILE)
            for i, w in enumerate(data['vocabulary']):
                if w['id'] == wid:
                    data['vocabulary'][i] = {**w, **changes, 'id': wid}
                    self._jsave(VOCAB_FILE, data)
                    return data['vocabulary'][i]
            return None

    def delete_word(self, wid):
        if self.cloud:
            self._sb.table('vocabulary').delete().eq('id', wid).execute()
        else:
            data = self._jload(VOCAB_FILE)
            data['vocabulary'] = [w for w in data['vocabulary'] if w['id'] != wid]
            self._jsave(VOCAB_FILE, data)

    def bulk_import(self, words):
        existing = {
            (w['deutsch'].strip().lower(), w['italienisch'].strip().lower())
            for w in self.get_vocabulary()
        }
        new_words, added, skipped = [], 0, 0
        for word in words:
            de = (word.get('deutsch') or '').strip()
            it = (word.get('italienisch') or '').strip()
            if not de or not it:
                continue
            pair = (de.lower(), it.lower())
            if pair in existing:
                skipped += 1
                continue
            existing.add(pair)
            word.update(id=str(uuid.uuid4()), added_date=datetime.now().isoformat(),
                        deutsch=de, italienisch=it,
                        correct_count=0, wrong_count=0, streak=0, last_practiced=None)
            new_words.append(word)
            added += 1
        if new_words:
            if self.cloud:
                for i in range(0, len(new_words), 100):
                    self._sb.table('vocabulary').insert(new_words[i:i+100]).execute()
            else:
                data = self._jload(VOCAB_FILE)
                data['vocabulary'].extend(new_words)
                self._jsave(VOCAB_FILE, data)
        return added, skipped, len(self.get_vocabulary())

    def update_word_stats(self, wid, correct):
        if self.cloud:
            r = self._sb.table('vocabulary').select('*').eq('id', wid).execute()
            if not r.data:
                return
            w = r.data[0]
            changes = {'last_practiced': datetime.now().isoformat()}
            if correct:
                changes['correct_count'] = (w.get('correct_count') or 0) + 1
                changes['streak']        = (w.get('streak') or 0) + 1
            else:
                changes['wrong_count'] = (w.get('wrong_count') or 0) + 1
                changes['streak']      = 0
            self._sb.table('vocabulary').update(changes).eq('id', wid).execute()
        else:
            data = self._jload(VOCAB_FILE)
            for w in data['vocabulary']:
                if w['id'] == wid:
                    if correct:
                        w['correct_count'] = w.get('correct_count', 0) + 1
                        w['streak']        = w.get('streak', 0) + 1
                    else:
                        w['wrong_count'] = w.get('wrong_count', 0) + 1
                        w['streak']      = 0
                    w['last_practiced'] = datetime.now().isoformat()
                    break
            self._jsave(VOCAB_FILE, data)

    def bulk_update_stats(self, results):
        if self.cloud:
            for r in results:
                self.update_word_stats(r['word_id'], r['correct'])
        else:
            data = self._jload(VOCAB_FILE)
            by_id = {w['id']: w for w in data['vocabulary']}
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
            self._jsave(VOCAB_FILE, data)

    # ── tests ──────────────────────────────────────────────────────────────
    def get_tests(self):
        if self.cloud:
            return self._sb.table('tests').select('*').order('date').execute().data
        return self._jload(TESTS_FILE)['tests']

    def add_test(self, record):
        if self.cloud:
            # JSONB: results must be JSON-serialisable
            rec = dict(record)
            self._sb.table('tests').insert(rec).execute()
        else:
            data = self._jload(TESTS_FILE)
            data['tests'].append(record)
            self._jsave(TESTS_FILE, data)

    # ── settings ───────────────────────────────────────────────────────────
    def get_settings(self):
        if self.cloud:
            r = self._sb.table('settings').select('*').execute()
            return {row['key']: row['value'] for row in r.data}
        return self._jload(SETTINGS_FILE)

    def save_settings(self, updates):
        if self.cloud:
            for k, v in updates.items():
                self._sb.table('settings').upsert({'key': k, 'value': str(v)}).execute()
            return self.get_settings()
        else:
            data = self._jload(SETTINGS_FILE)
            data.update(updates)
            self._jsave(SETTINGS_FILE, data)
            return data

    # ── first-run seed for Supabase ────────────────────────────────────────
    def seed_if_empty(self):
        if not self.cloud:
            return
        vocab = self.get_vocabulary()
        if not vocab:
            seed = os.path.join(SEED_DIR, 'vokabeln.json')
            if os.path.exists(seed):
                with open(seed, 'r', encoding='utf-8') as f:
                    words = json.load(f).get('vocabulary', [])
                for i in range(0, len(words), 100):
                    self._sb.table('vocabulary').insert(words[i:i+100]).execute()
        settings = self.get_settings()
        if not settings:
            self._sb.table('settings').insert([
                {'key': 'student_name', 'value': 'Josef'},
                {'key': 'api_key',      'value': ''},
            ]).execute()


db = DataStore()

# ── helpers ────────────────────────────────────────────────────────────────
def grade(pct):
    if pct >= 90: return (1, 'Sehr gut',        '⭐')
    if pct >= 75: return (2, 'Gut',             '😊')
    if pct >= 60: return (3, 'Befriedigend',    '👍')
    if pct >= 50: return (4, 'Genügend',        '😐')
    return              (5, 'Nicht genügend',   '😔')

# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')

# ── settings ──────────────────────────────────────────────────────────────────
@app.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(db.get_settings())

@app.route('/api/settings', methods=['PUT'])
def save_settings_route():
    return jsonify(db.save_settings(request.json))

# ── vocabulary ────────────────────────────────────────────────────────────────
@app.route('/api/vocabulary', methods=['GET'])
def get_vocabulary():
    return jsonify(db.get_vocabulary())

@app.route('/api/vocabulary', methods=['POST'])
def add_word():
    w = request.json
    w.update(id=str(uuid.uuid4()), added_date=datetime.now().isoformat(),
             correct_count=0, wrong_count=0, streak=0, last_practiced=None)
    db.add_word(w)
    return jsonify(w), 201

@app.route('/api/vocabulary/<wid>', methods=['PUT'])
def update_word(wid):
    updated = db.update_word(wid, request.json)
    if updated is None:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(updated)

@app.route('/api/vocabulary/<wid>', methods=['DELETE'])
def delete_word(wid):
    db.delete_word(wid)
    return jsonify({'ok': True})

# ── import ────────────────────────────────────────────────────────────────────
@app.route('/api/import', methods=['POST'])
def import_vocabulary():
    words          = request.json.get('words', [])
    added, skipped, total = db.bulk_import(words)
    return jsonify({'added': added, 'skipped': skipped, 'total': total})

# ── OCR ───────────────────────────────────────────────────────────────────────
@app.route('/api/ocr', methods=['POST'])
def ocr_image():
    settings    = db.get_settings()
    api_key     = settings.get('api_key', '').strip()
    payload     = request.json
    image_b64   = payload.get('image_b64', '')
    media_type  = payload.get('media_type', 'image/jpeg')
    prompt_hint = payload.get('hint', '')

    if not image_b64:
        return jsonify({'error': 'Kein Bild übermittelt'}), 400
    if not api_key:
        return jsonify({'error': 'Kein Anthropic API-Key gesetzt.'}), 400
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model='claude-opus-4-6',
            max_tokens=1024,
            messages=[{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': image_b64}},
                {'type': 'text',  'text': (
                    'Extrahiere alle Vokabeln aus diesem Bild. '
                    'Gib AUSSCHLIESSLICH eine JSON-Liste zurück im Format: '
                    '[{"deutsch": "...", "italienisch": "..."}, ...]. '
                    'Keine Erklärungen, nur das JSON-Array. '
                    + (f'Hinweis: {prompt_hint}' if prompt_hint else '')
                )},
            ]}],
        )
        raw   = msg.content[0].text.strip()
        start = raw.find('['); end = raw.rfind(']') + 1
        if start == -1 or end == 0:
            return jsonify({'error': 'Keine Vokabeln erkannt', 'raw': raw}), 422
        pairs = json.loads(raw[start:end])
        return jsonify({'pairs': pairs, 'count': len(pairs)})
    except ImportError:
        return jsonify({'error': 'Anthropic-Bibliothek nicht installiert.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── test ─────────────────────────────────────────────────────────────────────
@app.route('/api/test/generate', methods=['POST'])
def generate_test():
    vocab = db.get_vocabulary()
    if len(vocab) < 4:
        return jsonify({'error': 'Mindestens 4 Vokabeln benötigt'}), 400

    body      = request.json or {}
    count     = body.get('count', 20)
    direction = body.get('direction', 'de_it')
    mode      = body.get('mode', 'multiple_choice')
    category  = body.get('category', '')

    if category:
        vocab = [w for w in vocab if w.get('category', '') == category]
        if len(vocab) < 4:
            return jsonify({'error': f'Kategorie "{category}" hat weniger als 4 Vokabeln'}), 400

    count = min(count, len(vocab))

    def priority(w):
        lp    = w.get('last_practiced')
        days  = (datetime.now() - datetime.fromisoformat(lp)).days if lp else 0
        total = w['correct_count'] + w['wrong_count']
        acc   = w['correct_count'] / total if total else 0
        return acc - days * 0.05

    sorted_v = sorted(vocab, key=priority)
    n_prio   = int(count * 0.7)
    selected = sorted_v[:n_prio]
    rest     = [w for w in vocab if w not in selected]
    if rest:
        selected += random.sample(rest, min(count - len(selected), len(rest)))
    random.shuffle(selected)

    questions = []
    for word in selected:
        q = word['deutsch']     if direction == 'de_it' else word['italienisch']
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
            'word_id': word['id'], 'question': q, 'correct_answer': a,
            'choices': choices,    'mode': mode,
        })
    return jsonify({'questions': questions, 'direction': direction})

@app.route('/api/test/submit', methods=['POST'])
def submit_test():
    body      = request.json
    results   = body.get('results', [])
    direction = body.get('direction', 'de_it')

    correct_cnt      = sum(1 for r in results if r['correct'])
    total            = len(results)
    pct              = round(correct_cnt / total * 100) if total else 0
    gnum, gtxt, gemo = grade(pct)

    db.bulk_update_stats(results)

    record = dict(
        id=str(uuid.uuid4()), date=datetime.now().isoformat(),
        direction=direction, total=total, correct=correct_cnt,
        percentage=pct, grade=gnum, grade_text=gtxt, grade_emoji=gemo,
        results=results,
    )
    db.add_test(record)
    return jsonify({**record, 'wrong_words': [r for r in results if not r['correct']]})

# ── practice feedback ─────────────────────────────────────────────────────────
@app.route('/api/practice/update', methods=['POST'])
def practice_update():
    body = request.json
    db.update_word_stats(body['word_id'], body['correct'])
    return jsonify({'ok': True})

# ── stats ─────────────────────────────────────────────────────────────────────
@app.route('/api/stats', methods=['GET'])
def get_stats():
    vocab = db.get_vocabulary()
    tests = db.get_tests()

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
def get_tests_route():
    return jsonify(db.get_tests())

# ── categories ────────────────────────────────────────────────────────────────
@app.route('/api/categories', methods=['GET'])
def get_categories():
    vocab  = db.get_vocabulary()
    cats   = sorted({w.get('category', 'Allgemein') for w in vocab if w.get('category')})
    counts = {c: sum(1 for w in vocab if w.get('category') == c) for c in cats}
    return jsonify([{'name': c, 'count': counts[c]} for c in cats])

# ── translate ─────────────────────────────────────────────────────────────────
@app.route('/api/translate', methods=['POST'])
def translate():
    body      = request.json or {}
    text      = body.get('text', '').strip()
    direction = body.get('direction', 'auto')
    if not text:
        return jsonify({'error': 'Kein Text eingegeben'}), 400

    vocab      = db.get_vocabulary()
    text_lower = text.lower()
    matches    = []
    for w in vocab:
        if direction in ('de_it', 'auto') and w['deutsch'].lower() == text_lower:
            matches.append({'source': w['deutsch'], 'translation': w['italienisch'],
                            'direction': 'de_it', 'source_label': 'aus Vokabeln'})
        if direction in ('it_de', 'auto') and w['italienisch'].lower() == text_lower:
            matches.append({'source': w['italienisch'], 'translation': w['deutsch'],
                            'direction': 'it_de', 'source_label': 'aus Vokabeln'})
    if matches:
        return jsonify({'results': matches, 'source': 'vocabulary'})

    settings = db.get_settings()
    api_key  = settings.get('api_key', '').strip()
    if not api_key:
        return jsonify({'error': 'Wort nicht in Vokabeln. Bitte API-Key in Einstellungen eintragen.'}), 404

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        if direction == 'de_it':
            prompt = f'Übersetze diesen deutschen Text ins Italienische. Antworte NUR mit der Übersetzung:\n{text}'
        elif direction == 'it_de':
            prompt = f'Traduci questo testo italiano in tedesco. Rispondi SOLO con la traduzione:\n{text}'
        else:
            prompt = (f'Erkenne die Sprache und übersetze in die andere. '
                      f'Format: "SPRACHE: [Sprache] | ÜBERSETZUNG: [Text]"\nText: {text}')
        msg    = client.messages.create(model='claude-haiku-4-5-20251001', max_tokens=256,
                                        messages=[{'role': 'user', 'content': prompt}])
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

# ── homework ──────────────────────────────────────────────────────────────────
@app.route('/api/homework/upload', methods=['POST'])
def homework_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Keine Datei hochgeladen'}), 400
    file  = request.files['file']
    fname = (file.filename or '').lower()
    try:
        if fname.endswith('.docx'):
            try:
                import docx
            except ImportError:
                return jsonify({'error': 'python-docx nicht installiert.'}), 500
            from io import BytesIO
            doc   = docx.Document(BytesIO(file.read()))
            lines = [p.text for p in doc.paragraphs if p.text.strip()]
            content = '\n'.join(lines)
        elif fname.endswith('.pdf'):
            try:
                import pdfplumber
            except ImportError:
                return jsonify({'error': 'pdfplumber nicht installiert.'}), 500
            from io import BytesIO
            with pdfplumber.open(BytesIO(file.read())) as pdf:
                pages = [p.extract_text() or '' for p in pdf.pages]
            content = '\n\n'.join(p for p in pages if p.strip())
        else:
            return jsonify({'error': 'Nur .docx und .pdf werden unterstützt'}), 400
        if not content.strip():
            return jsonify({'error': 'Kein Text im Dokument gefunden'}), 422
        return jsonify({'content': content, 'filename': file.filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ── local IP helper ───────────────────────────────────────────────────────────
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

# ══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════════════════
def ensure_files():
    if not db.cloud:
        db._ensure_local()
    else:
        db.seed_if_empty()

if __name__ == '__main__':
    ensure_files()
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'reconfigure') else None

    port     = int(os.environ.get('PORT', 5000))
    is_cloud = bool(os.environ.get('PORT') or os.environ.get('RENDER') or os.environ.get('RAILWAY_ENVIRONMENT'))

    mode = 'Supabase' if db.cloud else 'Lokal (JSON)'
    print('=' * 55)
    print("  Josef's Vokabeltrainer DE <> IT")
    print(f'  Datenspeicher: {mode}')
    print('=' * 55)

    if not is_cloud:
        import threading, webbrowser, time
        local_ip = get_local_ip()
        print(f'  PC:       http://localhost:{port}')
        print(f'  iPhone:   http://{local_ip}:{port}')
        print('  (Fenster offen lassen!)')
        print('=' * 55)
        def _open():
            time.sleep(1.2)
            webbrowser.open(f'http://localhost:{port}')
        threading.Thread(target=_open, daemon=True).start()

    app.run(debug=False, port=port, host='0.0.0.0', use_reloader=False)
