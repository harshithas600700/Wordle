# Guess The Word

A web-based "Guess the Word" game built using **Flask** and **SQLite**. This project allows users to register, play up to three games a day, and administrators to view game reports. 

## Features
- **User Accounts**: Register and login as a player.
- **Daily Limits**: Players can play up to 3 games per day.
- **Gameplay**: Guess a 5-letter word within 5 attempts.
- **Admin Dashboard**: Admins can view daily statistics and player performance reports.

## Prerequisites
- Python 3.8+
- `pip` (Python package manager)

## Installation & Setup

1. **Set up a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize the Database**:
   ```bash
   flask --app app init-db
   ```
   *This creates the SQLite database (`guess_the_word.db`) and seeds it with the initial word list.*

4. **Run the Application**:
   ```bash
   flask --app app run
   ```

The application will be available at `http://127.0.0.1:5000`.

## Usage

### Playing the Game
1. Open the app in your browser and click **Register** to create a player account. (Username requires 1 lowercase, 1 uppercase, and 5+ letters. Password requires 1 letter, 1 number, 1 special char, 5+ length).
2. **Login** and click **Play** to start guessing. You have 5 tries to guess the 5-letter word

### Admin Access
The registration page creates only `player` accounts. To create an `admin` account, you can use the Flask shell:

```bash
flask --app app shell
```
```python
>>> from app import get_db
>>> from werkzeug.security import generate_password_hash
>>> db = get_db()
>>> db.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')", ('AdminUser', generate_password_hash('Admin1$')))
>>> db.commit()
>>> exit()
```
Now log in as `AdminUser` (password: `Admin1$`) to access the admin dashboard at `/admin/reports`.

## Running Tests

To run the automated test suite, use the following command:
```bash
python3 -m unittest discover -s tests
```
