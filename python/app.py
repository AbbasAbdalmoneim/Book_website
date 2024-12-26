from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import os
import PyPDF2
import re
from pymongo import MongoClient
from bson.objectid import ObjectId
import requests
from flask_caching import Cache
from bs4 import BeautifulSoup
import random

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*"}})

# Set up MongoDB connection
client = MongoClient('mongodb://localhost:27017/')  # Replace with MongoDB Atlas URL if needed
db = client['bookstore']
books_collection = db['books']

# Upload folder for PDFs and images
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Set up Flask caching (removed cache from search route to avoid issues)
cache = Cache(app, config={'CACHE_TYPE': 'simple'})

# Function to scrape quotes from quotes.toscrape.com (if still needed)
def get_quotes():
    end_quotes = []
    try:
        url = f"http://quotes.toscrape.com/"
        response = requests.get(url)
        soup = BeautifulSoup(response.text, "html.parser")

        quotes = soup.find_all("div", {"class": "quote"})
        for quote in quotes:
            text = quote.find("span", {"class": "text"}).text.strip()
            author = quote.find("small", {"class": "author"}).text.strip()
            end_quotes.append({"text": text, "author": author})

    except requests.exceptions.RequestException as e:
        print(f"Error while scraping quotes: {e}")

    return end_quotes

# Create a text index on the 'text' field for faster search
books_collection.create_index([('text', 'text')])

# Route for the home page (index)
@app.route('/')
def index():
    books = books_collection.find()  # Fetch all books from MongoDB
    return render_template('index.html', books=books)

# API Route for random quotes
@app.route('/api/random_quote', methods=['GET'])
def random_quote_api():
    quotes = get_quotes()  # Fetch quotes from the scraping function
    if quotes:
        random_quote = random.choice(quotes)  # Get a random quote
        return jsonify({"text": random_quote['text'], "author": random_quote['author']})
    else:
        return jsonify({"error": "No quotes available"}), 404

# Route to display random quotes
@app.route('/quote')
def quote_page():
    quotes = get_quotes()  # Fetch quotes from the scraping function
    if quotes:
        random_quote = random.choice(quotes)  # Get a random quote
        return render_template('quote_page.html', quote=random_quote)
    else:
        return render_template('quote_page.html', quote=None)

# Function to perform regex search and extract sentence context (only 9 words)
def perform_regex_search(text, search_term, num_words=9):
    # Adjust the number of words to be extracted around the search term
    half_window = num_words // 2
    pattern = re.compile(
        r'(\b(?:\w+\W+){0,' + str(half_window) + r'}\b' + re.escape(search_term) + 
        r'\b(?:\W+\w+){0,' + str(half_window) + r'})', 
        re.IGNORECASE
    )
    matches = pattern.findall(text)
    
    # Normalize and clean up matches
    truncated_matches = []
    for match in matches:
        words = match.split()
        search_term_lower = search_term.lower()
        if search_term_lower in [w.lower() for w in words]:
            truncated_matches.append(' '.join(words))
    
    return truncated_matches



@app.route('/search', methods=['GET', 'POST'])
def search_books():
    if request.method == 'POST':
        selected_book_id = request.form.get('book_id')
        search_term = request.form.get('search_term')

        if not selected_book_id or not search_term:
            return jsonify({'error': 'Please select a book and enter a search term.'}), 400

        try:
            book = books_collection.find_one({"_id": ObjectId(selected_book_id)})
            if not book:
                return jsonify({'error': 'Book not found.'}), 404

            text = book.get('text', '')
            matches = perform_regex_search(text, search_term)

            if matches:
                return jsonify({
                    'search_term': search_term,
                    'book_name': book.get('filename', 'Unknown'),
                    'results': matches
                })

            return jsonify({
                'search_term': search_term,
                'book_name': book.get('filename', 'Unknown'),
                'results': None
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # For GET requests, return the search page
    books = list(books_collection.find())
    return render_template('search_books.html', books=books)

@app.route('/api/books_list', methods=['GET'])
def getBooksList():
    try:
        fileNames = []
        books = list(books_collection.find())
        for book in books:
            fileNames.append({ 'id':str(book['_id']) , 'name':book['filename'], 'image':book['image']})
            
        return jsonify(fileNames)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    
# Route to handle PDF and image upload and save to MongoDB
@app.route('/upload_book', methods=['GET', 'POST'])
def upload_book():
    try:
        if request.method == 'POST':
            if 'pdf' not in request.files or 'image' not in request.files:
                return "Both book and image are required", 400
            pdf_file = request.files['pdf']
            image_file = request.files['image']
            if pdf_file.filename == '' or image_file.filename == '':
                return "Both book and image must be selected", 400
            if pdf_file and pdf_file.filename.endswith('.pdf') and image_file:
                pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename)
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], image_file.filename)
                pdf_file.save(pdf_path)
                image_file.save(image_path)
                text = extract_text_from_pdf(pdf_path)
                book_data = {
                    'filename': pdf_file.filename,
                    'image': image_file.filename,
                    'text': text
                }
                books_collection.insert_one(book_data)
                return jsonify({'message': 'Book uploaded successfully.'}), 201
    except Exception as e:
        return jsonify({'error': "upload file failed"}), 500
    # return render_template('upload_book.html')

# Function to extract text from PDF using PyPDF2
def extract_text_from_pdf(filepath):
    text = ""
    with open(filepath, 'rb') as file:
        reader = PyPDF2.PdfReader(file)
        for page in range(len(reader.pages)):
            text += reader.pages[page].extract_text()
    return text




if __name__ == '__main__':
    app.run(debug=True)
