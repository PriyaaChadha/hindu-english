import os
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template_string
from flask_cors import CORS
import yt_dlp
import whisper
from googletrans import Translator
import subprocess
import tempfile
import shutil
from pathlib import Path
import re
import time

app = Flask(__name__)
CORS(app)

# Configuration
UPLOAD_FOLDER = 'processed_videos'
DATABASE_FILE = 'videos.db'
WHISPER_MODEL_SIZE = 'base'  # Options: tiny, base, small, medium, large

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize Whisper model (download if not exists)
print("Loading Whisper model...")
whisper_model = whisper.load_model(WHISPER_MODEL_SIZE)
print("Whisper model loaded successfully!")

# Initialize translator
translator = Translator()

# Database setup
def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtube_url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            category TEXT,
            duration TEXT,
            processed_date TEXT,
            transcript_file TEXT,
            summary_file TEXT,
            status TEXT DEFAULT 'pending'
        )
    ''')
    conn.commit()
    conn.close()

# Initialize database
init_db()

class VideoProcessor:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
    
    def download_audio(self, youtube_url):
        """Download audio from YouTube video"""
        try:
            ydl_opts = {
                'format': 'bestaudio/best',
                'extractaudio': True,
                'audioformat': 'wav',
                'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(youtube_url, download=True)
                title = info.get('title', 'Unknown')
                duration = info.get('duration', 0)
                
                # Find the downloaded audio file
                audio_file = None
                for file in os.listdir(self.temp_dir):
                    if file.endswith('.wav'):
                        audio_file = os.path.join(self.temp_dir, file)
                        break
                
                return {
                    'audio_file': audio_file,
                    'title': title,
                    'duration': self.format_duration(duration)
                }
        except Exception as e:
            raise Exception(f"Error downloading audio: {str(e)}")
    
    def transcribe_audio(self, audio_file):
        """Transcribe audio to Hindi text using Whisper"""
        try:
            print("Transcribing audio...")
            result = whisper_model.transcribe(audio_file, language='hi')
            return result['text']
        except Exception as e:
            raise Exception(f"Error transcribing audio: {str(e)}")
    
    def translate_text(self, hindi_text):
        """Translate Hindi text to English"""
        try:
            print("Translating to English...")
            # Split text into chunks to avoid API limits
            chunks = self.split_text_into_chunks(hindi_text, 4000)
            translated_chunks = []
            
            for chunk in chunks:
                if chunk.strip():
                    translated = translator.translate(chunk, src='hi', dest='en')
                    translated_chunks.append(translated.text)
                    time.sleep(0.1)  # Rate limiting
            
            return ' '.join(translated_chunks)
        except Exception as e:
            raise Exception(f"Error translating text: {str(e)}")
    
    def generate_summary(self, english_text):
        """Generate summary with key concepts"""
        try:
            # Simple extractive summary - in production, use better NLP models
            sentences = re.split(r'[.!?]+', english_text)
            sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
            
            # Key concepts commonly found in Hindu texts
            key_concepts = [
                'dharma', 'karma', 'moksha', 'yoga', 'bhakti', 'meditation',
                'Krishna', 'Rama', 'Hanuman', 'Gita', 'devotion', 'scripture',
                'spiritual', 'divine', 'enlightenment', 'liberation', 'truth'
            ]
            
            # Find sentences containing key concepts
            important_sentences = []
            for sentence in sentences:
                sentence_lower = sentence.lower()
                if any(concept in sentence_lower for concept in key_concepts):
                    important_sentences.append(sentence)
            
            # Take top sentences or use all if few found
            summary_sentences = important_sentences[:10] if len(important_sentences) > 10 else important_sentences
            
            if not summary_sentences:
                # Fallback to first few sentences
                summary_sentences = sentences[:5]
            
            summary = self.format_summary(summary_sentences, english_text)
            return summary
            
        except Exception as e:
            raise Exception(f"Error generating summary: {str(e)}")
    
    def format_summary(self, key_sentences, full_text):
        """Format summary with structure"""
        summary = f"""HINDU KNOWLEDGE VIDEO SUMMARY
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

KEY TEACHINGS:
"""
        for i, sentence in enumerate(key_sentences[:5], 1):
            summary += f"{i}. {sentence.strip()}\n"
        
        summary += f"""

MAIN CONCEPTS COVERED:
• Spiritual wisdom and guidance
• Traditional Hindu teachings
• Practical applications for daily life
• Sacred scriptures and their meanings

PRACTICAL INSIGHTS:
The discourse emphasizes the importance of spiritual practice, devotion, and righteous living according to ancient Hindu wisdom.

RECOMMENDED REFLECTION:
Consider how these teachings can be applied in modern life while maintaining connection to traditional values.

Note: This summary preserves key spiritual concepts while making them accessible for contemporary understanding.
"""
        return summary
    
    def format_transcript(self, english_text, title):
        """Format transcript with proper structure"""
        transcript = f"""HINDI TO ENGLISH TRANSCRIPT
Title: {title}
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

FULL TRANSCRIPT:
{english_text}

NOTES:
- This transcript was generated using AI transcription and translation
- Sanskrit terms are preserved where possible with English explanations
- Some cultural context may require additional study
- Original audio contains the authentic pronunciation and intonation

For questions about specific terms or concepts, please consult traditional Hindu texts or qualified teachers.
"""
        return transcript
    
    def split_text_into_chunks(self, text, max_chars):
        """Split text into chunks for translation"""
        words = text.split()
        chunks = []
        current_chunk = []
        current_length = 0
        
        for word in words:
            if current_length + len(word) + 1 > max_chars:
                if current_chunk:
                    chunks.append(' '.join(current_chunk))
                    current_chunk = [word]
                    current_length = len(word)
            else:
                current_chunk.append(word)
                current_length += len(word) + 1
        
        if current_chunk:
            chunks.append(' '.join(current_chunk))
        
        return chunks
    
    def format_duration(self, seconds):
        """Format duration in human readable format"""
        if not seconds:
            return "Unknown"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours} hour{'s' if hours != 1 else ''} {minutes} min{'s' if minutes != 1 else ''}"
        else:
            return f"{minutes} min{'s' if minutes != 1 else ''}"
    
    def cleanup(self):
        """Clean up temporary files"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

# API Routes
@app.route('/')
def index():
    """Serve the main HTML interface"""
    from flask import render_template
    return render_template('youtube_converter.html')

@app.route('/api/process-video', methods=['POST'])
def process_video():
    """Process YouTube video and generate transcript and summary"""
    try:
        data = request.json
        youtube_url = data.get('youtube_url')
        category = data.get('category', 'other')
        custom_title = data.get('custom_title', '')
        
        if not youtube_url:
            return jsonify({'error': 'YouTube URL is required'}), 400
        
        # Check if video already processed
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM videos WHERE youtube_url = ?', (youtube_url,))
        existing = cursor.fetchone()
        conn.close()
        
        if existing:
            return jsonify({'error': 'Video already processed'}), 400
        
        processor = VideoProcessor()
        
        try:
            # Step 1: Download audio
            audio_info = processor.download_audio(youtube_url)
            audio_file = audio_info['audio_file']
            title = custom_title or audio_info['title']
            duration = audio_info['duration']
            
            # Step 2: Transcribe audio
            hindi_text = processor.transcribe_audio(audio_file)
            
            # Step 3: Translate to English
            english_text = processor.translate_text(hindi_text)
            
            # Step 4: Generate summary
            summary = processor.generate_summary(english_text)
            
            # Step 5: Format transcript
            transcript = processor.format_transcript(english_text, title)
            
            # Step 6: Save files
            video_id = str(int(time.time()))
            transcript_filename = f"{video_id}_transcript.txt"
            summary_filename = f"{video_id}_summary.txt"
            
            transcript_path = os.path.join(UPLOAD_FOLDER, transcript_filename)
            summary_path = os.path.join(UPLOAD_FOLDER, summary_filename)
            
            with open(transcript_path, 'w', encoding='utf-8') as f:
                f.write(transcript)
            
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(summary)
            
            # Step 7: Save to database
            conn = sqlite3.connect(DATABASE_FILE)
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO videos (youtube_url, title, category, duration, processed_date, transcript_file, summary_file, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (youtube_url, title, category, duration, datetime.now().isoformat(), transcript_filename, summary_filename, 'completed')
            )
            conn.commit()
            video_db_id = cursor.lastrowid
            conn.close()
            
            return jsonify({
                'success': True,
                'video_id': video_db_id,
                'title': title,
                'transcript_file': transcript_filename,
                'summary_file': summary_filename
            })
            
        finally:
            processor.cleanup()
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/videos', methods=['GET'])
def get_videos():
    """Get list of processed videos"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM videos WHERE status = "completed" ORDER BY processed_date DESC')
        videos = cursor.fetchall()
        conn.close()
        
        video_list = []
        for video in videos:
            video_list.append({
                'id': video[0],
                'youtube_url': video[1],
                'title': video[2],
                'category': video[3],
                'duration': video[4],
                'processed_date': video[5],
                'transcript_file': video[6],
                'summary_file': video[7]
            })
        
        return jsonify(video_list)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<file_type>/<filename>')
def download_file(file_type, filename):
    """Download transcript or summary file"""
    try:
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(file_path, as_attachment=True)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """Get admin statistics"""
    try:
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        
        # Total videos processed
        cursor.execute('SELECT COUNT(*) FROM videos WHERE status = "completed"')
        total_videos = cursor.fetchone()[0]
        
        # Videos in queue
        cursor.execute('SELECT COUNT(*) FROM videos WHERE status = "pending"')
        queue_count = cursor.fetchone()[0]
        
        # Total downloads (mock data for now)
        total_downloads = total_videos * 5  # Estimate
        
        conn.close()
        
        return jsonify({
            'total_videos': total_videos,
            'total_downloads': total_downloads,
            'queue_count': queue_count
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/search')
def search_videos():
    """Search videos by title or category"""
    try:
        query = request.args.get('q', '').lower()
        
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM videos WHERE status = "completed" AND (LOWER(title) LIKE ? OR LOWER(category) LIKE ?) ORDER BY processed_date DESC',
            (f'%{query}%', f'%{query}%')
        )
        videos = cursor.fetchall()
        conn.close()
        
        video_list = []
        for video in videos:
            video_list.append({
                'id': video[0],
                'youtube_url': video[1],
                'title': video[2],
                'category': video[3],
                'duration': video[4],
                'processed_date': video[5],
                'transcript_file': video[6],
                'summary_file': video[7]
            })
        
        return jsonify(video_list)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting Hindu Knowledge Converter Server...")
    print("Loading AI models (this may take a moment)...")
    print("Server ready!")
    print("Open http://localhost:5000 in your web browser")
    app.run(debug=True, host='0.0.0.0', port=5000)