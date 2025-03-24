import sqlite3
import uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash, g
from flask_socketio import SocketIO, send
import hashlib


app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
DATABASE = 'market.db'
socketio = SocketIO(app)

# 데이터베이스 연결 관리: 요청마다 연결 생성 후 사용, 종료 시 close
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row  # 결과를 dict처럼 사용하기 위함
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# 테이블 생성(최초 실행 시에만)
def init_db():
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        # 사용자 테이블 생성 - 송금을 위한 money 필드 추가
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                money INTEGER NOT NULL DEFAULT 10000, 
                bio TEXT
            )
        """)
        # 상품 테이블 생성
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS product (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                price TEXT NOT NULL,
                seller_id TEXT NOT NULL
            )
        """)
        # 신고 테이블 생성 - 신고자의 편의를 위한 target_username 필드 추가
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS report (
                id TEXT PRIMARY KEY,
                reporter_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                target_username TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)

        db.commit()

# 기본 라우트
@app.route('/')
def index():
    if 'user_id' in session and 'user_username' in session:
        return redirect(url_for('home'))
    return render_template('index.html')

# 회원가입
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # 사용자명 안전성 검사
        if not username.isalpha():
            flash('사용자명은 알파벳으로만 구성되어야 합니다.')
            return redirect(url_for('register'))
        # 비밀번호 안전성 검사
        if len(password) < 8 or not any(char.isdigit() for char in password) or not any(char.isalpha() for char in password):
            flash('비밀번호는 8자 이상이어야 하며, 알파벳과 숫자를 적어도 하나씩 포함해야 합니다.')
            return redirect(url_for('register'))
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        db = get_db()
        cursor = db.cursor()
        # 중복 사용자 체크
        cursor.execute("SELECT * FROM user WHERE username = ?", (username,))
        if cursor.fetchone() is not None:
            flash('이미 존재하는 사용자명입니다.')
            return redirect(url_for('register'))
        user_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO user (id, username, password) VALUES (?, ?, ?)",
                       (user_id, username, password_hash))
        db.commit()
        flash('회원가입이 완료되었습니다. 로그인 해주세요.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # 비밀번호 해시화
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM user WHERE username = ? AND password = ?", (username, password_hash))
        user = cursor.fetchone()
        # SQL injection 차단
        if not username.isalpha():
            flash('사용자명은 알파벳으로만 구성되어야 합니다.')
            return redirect(url_for('login'))
        if user:
            session['user_id'] = user['id']
            session['user_username'] = user['username']
            flash('로그인 성공!')
            return redirect(url_for('home'))
        else:
            flash('로그인 실패: 아이디 또는 비밀번호가 올바르지 않습니다.')
            return redirect(url_for('login'))
    return render_template('login.html')

# 로그아웃
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_username', None)
    flash('로그아웃되었습니다.')
    return redirect(url_for('index'))

# 홈 화면
@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    # 현재 사용자 조회
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    # 모든 상품 조회
    cursor.execute("SELECT * FROM product")
    all_products = cursor.fetchall()
    return render_template('home.html', products=all_products, user=current_user)

# 프로필 페이지: bio 업데이트 가능
@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    if request.method == 'POST':
        bio = request.form.get('bio', '')
        cursor.execute("UPDATE user SET bio = ? WHERE id = ?", (bio, session['user_id']))
        db.commit()
        flash('프로필이 업데이트되었습니다.')
        return redirect(url_for('profile'))
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    return render_template('profile.html', user=current_user)

# 상품 등록
@app.route('/product/new', methods=['GET', 'POST'])
def new_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        price = request.form['price']
        db = get_db()
        cursor = db.cursor()
        product_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO product (id, title, description, price, seller_id) VALUES (?, ?, ?, ?, ?)",
            (product_id, title, description, price, session['user_id'])
        )
        db.commit()
        flash('상품이 등록되었습니다.')
        return redirect(url_for('home'))
    return render_template('new_product.html')

# 상품 상세보기
@app.route('/product/<product_id>')
def view_product(product_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM product WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    if not product:
        flash('상품을 찾을 수 없습니다.')
        return redirect(url_for('home'))
    cursor.execute("SELECT * FROM user WHERE id = ?", (product['seller_id'],))
    seller = cursor.fetchone()
    return render_template('view_product.html', product=product, seller=seller)

@app.route('/report', methods=['GET', 'POST'])
def report():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        target_username = request.form['target_username']
        reason = request.form['reason']
        
        # 사용자 이름을 가져오는 코드 추가
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM user WHERE username = ?", (target_username,))
        target_user = cursor.fetchone()
        
        # target_user가 존재하지 않으면 오류 처리
        if not target_user:
            flash('사용자를 찾을 수 없습니다.')
            return redirect(url_for('report'))
        
        target_id = target_user['id'] 
        
        report_id = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO report (id, reporter_id, target_id, target_username, reason) VALUES (?, ?, ?, ?, ?)",
            (report_id, session['user_id'], target_id, target_username, reason)
        )
        db.commit()
        
        flash('신고가 접수되었습니다.')
        return redirect(url_for('home'))
    
    return render_template('report.html')

# 신고 목록 보기(관리자 전용)
@app.route('/viewreports')
def view_reports():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    if current_user['username'] != 'admin':
        flash('접근 권한이 없습니다.')
        return redirect(url_for('home'))
    cursor.execute("SELECT * FROM report")
    reports = cursor.fetchall()
    return render_template('view_reports.html', reports=reports)

# 사용자 삭제(관리자 전용)
@app.route('/deluser', methods=['GET', 'POST'])
def delete_user():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    if current_user['username'] != 'admin':
        flash('접근 권한이 없습니다.')
        return redirect(url_for('home'))
    if request.method == 'POST':
        target_id = request.form['target_id']
        cursor.execute("SELECT * FROM user WHERE id = ?", (target_id,))
        target_user = cursor.fetchone()
        if not target_user:
            flash('사용자를 찾을 수 없습니다.')
            return redirect(url_for('delete_user'))
        cursor.execute("DELETE FROM user WHERE id = ?", (target_id,))
        db.commit()
        flash('사용자가 삭제되었습니다.')
        return redirect(url_for('delete_user'))
    return render_template('deluser.html')

# 상품 삭제(관리자 전용)
@app.route('/delproduct', methods=['GET', 'POST'])
def delete_product():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    if current_user['username'] != 'admin':
        flash('접근 권한이 없습니다.')
        return redirect(url_for('home'))
    if request.method == 'POST':
        target_id = request.form['target_id']
        cursor.execute("SELECT * FROM product WHERE id = ?", (target_id,))
        product = cursor.fetchone()
        if not product:
            flash('상품을 찾을 수 없습니다.')
            return redirect(url_for('delete_product'))
        cursor.execute("DELETE FROM product WHERE id = ?", (target_id,))
        db.commit()
        flash('상품이 삭제되었습니다.')
        return redirect(url_for('delete_product'))
    return render_template('delproduct.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('query', '') 
    db = get_db()
    cursor = db.cursor()

    if query:
        # 상품 검색
        cursor.execute("SELECT * FROM product WHERE title LIKE ?", ('%' + query + '%',))
        all_products = cursor.fetchall()
    else:
        # 검색어가 없으면 모든 상품을 반환
        cursor.execute("SELECT * FROM product")
        all_products = cursor.fetchall()

    return render_template('search.html', products=all_products, query=query)


# 송금하기
@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if request.method == 'POST':
        recipient_username = request.form['recipient_username']
        amount = int(request.form['amount'])
        db = get_db()
        cursor = db.cursor()
        # 수신자 확인
        cursor.execute("SELECT * FROM user WHERE username = ?", (recipient_username,))
        recipient = cursor.fetchone()
        if not recipient:
            flash('수신자를 찾을 수 없습니다.')
            return redirect(url_for('transfer'))
        # 송금자 확인
        cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
        sender = cursor.fetchone()
        if sender['money'] < 1:
            flash('잘못된 금액입니다.')
            return redirect(url_for('transfer'))
        if sender['money'] < amount:
            flash('잔액이 부족합니다.')
            return redirect(url_for('transfer'))
        # 송금 처리
        cursor.execute("UPDATE user SET money = money - ? WHERE id = ?", (amount, session['user_id']))
        cursor.execute("UPDATE user SET money = money + ? WHERE id = ?", (amount, recipient['id']))
        db.commit()
        flash(f'{amount}원이 {recipient_username}님에게 송금되었습니다.')
        return redirect(url_for('home'))
    return render_template('transfer.html')

# 돈 받기
@app.route('/showmethemoney')
def show_me_the_money():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE user SET money = money + 10000 WHERE id = ?", (session['user_id'],))
    db.commit()
    flash('10000원이 추가되었습니다.')
    return redirect(url_for('home'))

# 돈 많이 받기(관리자 전용)
@app.route('/showmemoremoney')
def show_me_more_money():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM user WHERE id = ?", (session['user_id'],))
    current_user = cursor.fetchone()
    if current_user['username'] != 'admin':
        flash('접근 권한이 없습니다.')
        return redirect(url_for('home'))
    cursor.execute("UPDATE user SET money = money + 1000000 WHERE id = ?", (session['user_id'],))
    db.commit()
    flash('1000000원이 추가되었습니다.')
    return redirect(url_for('home'))


# 실시간 채팅: 클라이언트가 메시지를 보내면 전체 브로드캐스트
@socketio.on('send_message')
def handle_send_message_event(data):
    data['message_id'] = str(uuid.uuid4())
    send(data, broadcast=True)

if __name__ == '__main__':
    init_db()  # 앱 컨텍스트 내에서 테이블 생성
    socketio.run(app, debug=True)
