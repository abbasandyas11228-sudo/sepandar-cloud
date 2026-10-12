import os, sqlite3, secrets
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
ROOT=Path(__file__).resolve().parent; DATA=ROOT/"data"; UPLOADS=DATA/"uploads"; DB=DATA/"cloud.db"
DATA.mkdir(exist_ok=True); UPLOADS.mkdir(parents=True,exist_ok=True)
app=Flask(__name__); app.secret_key=os.getenv("SECRET_KEY","dev-only-change-this-secret-before-deployment")
app.config["MAX_CONTENT_LENGTH"]=int(os.getenv("MAX_UPLOAD_MB","2048"))*1024*1024
CATEGORIES={"software":"نرم‌افزارها","updates":"نسخه‌ها و به‌روزرسانی‌ها","guides":"آموزش و راهنما","drivers":"ابزار و فایل‌های کاربردی","documents":"اسناد و فرم‌ها","other":"سایر فایل‌ها"}
def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
 with db() as c:
  c.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY CHECK(id=1),username TEXT NOT NULL,password_hash TEXT NOT NULL)")
  c.execute("""CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY AUTOINCREMENT,token TEXT UNIQUE NOT NULL,original_name TEXT NOT NULL,stored_name TEXT NOT NULL,size INTEGER NOT NULL,category TEXT NOT NULL DEFAULT 'other',description TEXT NOT NULL DEFAULT '',public INTEGER NOT NULL DEFAULT 1,downloads INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
  cols={x["name"] for x in c.execute("PRAGMA table_info(files)")}
  for n,d in [("category","TEXT NOT NULL DEFAULT 'other'"),("description","TEXT NOT NULL DEFAULT ''"),("public","INTEGER NOT NULL DEFAULT 1"),("downloads","INTEGER NOT NULL DEFAULT 0")]:
   if n not in cols: c.execute(f"ALTER TABLE files ADD COLUMN {n} {d}")
  if not c.execute("SELECT id FROM users WHERE id=1").fetchone():
   c.execute("INSERT INTO users VALUES(1,?,?)",(os.getenv("ADMIN_USERNAME","admin"),generate_password_hash(os.getenv("ADMIN_PASSWORD","ChangeMe-123!"))))
init()
def admin_only(fn):
 @wraps(fn)
 def w(*a,**kw):
  if not session.get("admin"): return redirect(url_for("login",next=request.path))
  return fn(*a,**kw)
 return w
def human_size(n):
 n=float(n)
 for u in ("B","KB","MB","GB","TB"):
  if n<1024 or u=="TB": return f"{int(n)} B" if u=="B" else f"{n:.1f} {u}"
  n/=1024
app.jinja_env.filters["filesize"]=human_size
@app.after_request
def headers(r):
 r.headers["X-Content-Type-Options"]="nosniff"; r.headers["X-Frame-Options"]="DENY"; r.headers["Referrer-Policy"]="strict-origin-when-cross-origin"; return r
@app.route("/")
def home():
 q=request.args.get("q","").strip(); cat=request.args.get("category","")
 sql="SELECT * FROM files WHERE public=1"; args=[]
 if q: sql+=" AND (original_name LIKE ? OR description LIKE ?)"; args += [f"%{q}%",f"%{q}%"]
 if cat in CATEGORIES: sql+=" AND category=?"; args.append(cat)
 sql+=" ORDER BY id DESC"
 with db() as c:
  rows=c.execute(sql,args).fetchall(); total=c.execute("SELECT COUNT(*) FROM files WHERE public=1").fetchone()[0]
  counts={r["category"]:r["n"] for r in c.execute("SELECT category,COUNT(*) n FROM files WHERE public=1 GROUP BY category")}
 return render_template("home.html",files=rows,q=q,category=cat,categories=CATEGORIES,counts=counts,total=total)
@app.route("/login",methods=["GET","POST"])
def login():
 if request.method=="POST":
  with db() as c: u=c.execute("SELECT * FROM users WHERE id=1").fetchone()
  if u and request.form.get("username","").strip()==u["username"] and check_password_hash(u["password_hash"],request.form.get("password","")):
   session.clear(); session["admin"]=True; return redirect(url_for("manage"))
  flash("نام کاربری یا رمز عبور صحیح نیست.","error")
 return render_template("login.html")
@app.post("/logout")
def logout(): session.clear(); return redirect(url_for("home"))
@app.route("/manage")
@admin_only
def manage():
 q=request.args.get("q","")
 with db() as c:
  rows=c.execute("SELECT * FROM files WHERE original_name LIKE ? ORDER BY id DESC",(f"%{q}%",)).fetchall()
  total=c.execute("SELECT COUNT(*) FROM files").fetchone()[0]; bytes_=c.execute("SELECT COALESCE(SUM(size),0) FROM files").fetchone()[0]; downloads=c.execute("SELECT COALESCE(SUM(downloads),0) FROM files").fetchone()[0]
 return render_template("manage.html",files=rows,q=q,categories=CATEGORIES,total=total,total_bytes=bytes_,downloads=downloads)
@app.post("/upload")
@admin_only
def upload():
 picked=request.files.getlist("files"); cat=request.form.get("category","other"); cat=cat if cat in CATEGORIES else "other"; desc=request.form.get("description","").strip()[:500]; public=1 if request.form.get("public")=="on" else 0; count=0
 with db() as c:
  for f in picked:
   if not f or not f.filename: continue
   original=Path(f.filename).name[:255]; safe=secure_filename(original) or "download"; stored=secrets.token_hex(16)+"_"+safe
   f.save(UPLOADS/stored); c.execute("INSERT INTO files(token,original_name,stored_name,size,category,description,public) VALUES(?,?,?,?,?,?,?)",(secrets.token_urlsafe(20),original,stored,(UPLOADS/stored).stat().st_size,cat,desc,public)); count+=1
 flash(f"{count} فایل بارگذاری شد." if count else "فایلی انتخاب نشده بود.","success" if count else "error"); return redirect(url_for("manage"))
@app.post("/visibility/<int:fid>")
@admin_only
def visibility(fid):
 with db() as c:
  r=c.execute("SELECT public FROM files WHERE id=?",(fid,)).fetchone()
  if not r: abort(404)
  c.execute("UPDATE files SET public=? WHERE id=?",(0 if r["public"] else 1,fid))
 flash("دسترسی فایل تغییر کرد.","success"); return redirect(url_for("manage"))
@app.post("/delete/<int:fid>")
@admin_only
def delete(fid):
 with db() as c:
  r=c.execute("SELECT * FROM files WHERE id=?",(fid,)).fetchone()
  if not r: abort(404)
  c.execute("DELETE FROM files WHERE id=?",(fid,))
 (UPLOADS/r["stored_name"]).unlink(missing_ok=True); flash("فایل و لینک آن حذف شد.","success"); return redirect(url_for("manage"))
@app.route("/d/<token>")
def download(token):
 with db() as c:
  r=c.execute("SELECT * FROM files WHERE token=?",(token,)).fetchone()
  if not r or (not r["public"] and not session.get("admin")): abort(404)
  c.execute("UPDATE files SET downloads=downloads+1 WHERE token=?",(token,))
 if not (UPLOADS/r["stored_name"]).is_file(): abort(404)
 return send_from_directory(UPLOADS,r["stored_name"],as_attachment=True,download_name=r["original_name"],conditional=True)
@app.route("/health")
def health(): return {"status":"ok"}
@app.errorhandler(413)
def too_large(_):
 flash("حجم فایل از سقف تعیین‌شده بیشتر است.","error"); return redirect(url_for("manage") if session.get("admin") else url_for("home"))
@app.errorhandler(404)
def missing(_): return render_template("404.html"),404
if __name__=="__main__": app.run(host="127.0.0.1",port=int(os.getenv("PORT","5000")),debug=False)
