from datetime import datetime
import random
from string import ascii_uppercase
from flask import Flask, render_template, request, session, redirect, url_for, flash, get_flashed_messages
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO, join_room, leave_room, send
import json
from sqlalchemy import JSON

app = Flask(__name__)
app.config["SECRET_KEY"] = "your_secret_key"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///chat.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)
socketio = SocketIO(app)

# Define models
class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(4), unique=True, nullable=False)
    messages = db.Column(JSON, nullable=True)  # Store messages as JSON

    def add_message(self, sender, message):
        if not self.messages:
            self.messages = json.dumps([])
        messages = json.loads(self.messages)
        messages.append({
            "sender": sender,
            "message": message,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        self.messages = json.dumps(messages)

# Define association table for user-room relationship
user_room_association = db.Table('user_room_association',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('room_id', db.Integer, db.ForeignKey('room.id'))
)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    rooms = db.relationship('Room', secondary=user_room_association, backref='users')

# Create tables
with app.app_context():
    db.create_all()

# Helper function to generate unique room codes
def generate_unique_code(length):
    while True:
        code = "".join(random.choices(ascii_uppercase, k=length))
        if not Room.query.filter_by(code=code).first():
            break
    return code

# Routes
@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        if "login" in request.form:
            return redirect(url_for("login"))
        elif "register" in request.form:
            return redirect(url_for("register"))
    return render_template("home.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        existing_user = User.query.filter_by(username=username).first()

        if existing_user:
            flash("Username already exists. Please choose a different one.", "error")
        else:
            new_user = User(username=username, password=password)
            db.session.add(new_user)
            db.session.commit()
            session["username"] = username
            return redirect(url_for("dashboard"))
        
    messages = get_flashed_messages()
    return render_template('register.html', messages=messages)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session["username"] = username
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")
    messages = get_flashed_messages()
    return render_template("login.html", messages=messages)

@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    username = session.get("username")
    if not username:
        return redirect(url_for("home"))

    user = User.query.filter_by(username=username).first()
    rooms = user.rooms if user.rooms else []

    if request.method == 'POST':
        if 'logout' in request.form:
            session.pop("username", None)
            return redirect(url_for('home'))
        elif 'create_room' in request.form:
            room_code = generate_unique_code(4)
            new_room = Room(code=room_code)
            user.rooms.append(new_room)
            db.session.add(new_room)
            db.session.commit()
            return redirect(url_for('room', code=room_code))
        elif 'join_room' in request.form:
            room_code = request.form.get('room_code')
            room = Room.query.filter_by(code=room_code).first()
            if room:
                user.rooms.append(room)
                db.session.commit()
                return redirect(url_for('room', code=room_code))
            else:
                flash("Room does not exist.", "error")

    return render_template('dashboard.html', username=username, rooms=rooms)

@app.route("/room/<string:code>", methods=['GET', 'POST'])
def room(code):
    username = session.get("username")
    if not username:
        return redirect(url_for("home"))

    user = User.query.filter_by(username=username).first()
    room = Room.query.filter_by(code=code).first()

    if not room:
        flash("Room does not exist.", "error")
        return redirect(url_for("dashboard"))

    session["room"] = code  # Set the room code in the session

    messages = json.loads(room.messages) if room.messages else []
    return render_template("room.html", username=username, room_code=code, messages=messages)


@socketio.on("message")
def handle_message(data):
    room_code = data.get("room_code")
    username = session.get("username")
    message_text = data.get("message")

    if not room_code or not username or not message_text:
        return

    room = Room.query.filter_by(code=room_code).first()
    if not room:
        return

    room.add_message(username, message_text)
    db.session.commit()

    content = {
        "sender": username,
        "message": message_text, 
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    send(content, room=room_code)

@socketio.on("connect")
def connect():
    username = session.get("username")
    room_code = request.args.get('code')
    if username and room_code:
        join_room(room_code)
        content = {
            "sender": username,
            "message": "has entered the room",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        socketio.emit('message', content, room=room_code)

@socketio.on("disconnect")
def disconnect():
    username = session.get("username")
    room_code = request.args.get('code')
    if username and room_code:
        leave_room(room_code)
        content = {
            "sender": username,
            "message": "has left the room",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        socketio.emit('message', content, room=room_code)

if __name__ == "__main__":
    socketio.run(app, debug=True)
