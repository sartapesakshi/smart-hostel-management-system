"""Fee management.

Two tables work together:
  fees      - what a student owes (type, amount, due date)
  payments  - every payment made against a fee (supports part-payments)
Status (Paid / Pending / Partial / Overdue) is derived by the fee_overview view.
Overdue = balance is still due AND the due date has passed (even if part-paid).
"""
import sqlite3

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, url_for)

import db
import helpers
from helpers import clean

bp = Blueprint("fees", __name__, url_prefix="/fees")


# ------------------------------------------------------- business rules
def record_payment(database, fee_id, amount, payment_date, method, reference):
    """Insert one payment (caller commits). Raises ValueError with a friendly message."""
    fee = database.execute("SELECT * FROM fee_overview WHERE id = ?", (fee_id,)).fetchone()
    if fee is None:
        raise ValueError("That fee does not exist.")
    if fee["balance"] <= 0:
        raise ValueError("This fee is already fully paid.")
    if amount > fee["balance"] + 0.001:
        raise ValueError(f"Payment of {helpers.inr(amount)} is more than the balance due ({helpers.inr(fee['balance'])}).")
    next_id = database.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM payments").fetchone()[0]
    receipt_no = f"RCPT-{payment_date[:4]}-{next_id:05d}"
    user_id = g.user["id"] if getattr(g, "user", None) else None
    cursor = database.execute(
        "INSERT INTO payments (fee_id, amount, payment_date, method, transaction_ref, receipt_no, received_by) "
        "VALUES (?,?,?,?,?,?,?)",
        (fee_id, amount, payment_date, method, reference or None, receipt_no, user_id))
    return cursor.lastrowid


def validate_payment(form):
    data = {"amount": clean(form.get("amount")), "payment_date": clean(form.get("payment_date")),
            "method": clean(form.get("method")), "transaction_ref": clean(form.get("transaction_ref"))}
    errors = {}
    if helpers.parse_amount(data["amount"]) is None:
        errors["amount"] = "Enter a positive amount (maximum 2 decimals)."
    paid_on = helpers.parse_date(data["payment_date"])
    if not paid_on:
        errors["payment_date"] = "Enter a valid payment date."
    elif paid_on > helpers.parse_date(helpers.today()):
        errors["payment_date"] = "Payment date cannot be in the future."
    if data["method"] not in helpers.PAYMENT_METHODS:
        errors["method"] = "Select a payment method."
    elif data["method"] != "Cash" and len(data["transaction_ref"]) < 4:
        errors["transaction_ref"] = "Enter the transaction / cheque / reference number."
    if len(data["transaction_ref"]) > 60:
        errors["transaction_ref"] = "Reference is too long."
    return data, errors


def validate_fee(form, editing_fee=None):
    data = {"student_id": clean(form.get("student_id")), "fee_type": clean(form.get("fee_type")),
            "amount": clean(form.get("amount")), "due_date": clean(form.get("due_date")),
            "notes": clean(form.get("notes"))}
    errors = {}
    if editing_fee is None:
        student = db.query_one("SELECT status FROM students WHERE id = ?",
                               (helpers.parse_int(data["student_id"], 1) or -1,))
        if student is None:
            errors["student_id"] = "Select a student."
        elif student["status"] == "Left":
            errors["student_id"] = "This student has left the hostel."
    if data["fee_type"] not in helpers.FEE_TYPES:
        errors["fee_type"] = "Select a fee type."
    amount = helpers.parse_amount(data["amount"])
    if amount is None:
        errors["amount"] = "Enter a positive amount (maximum 2 decimals, up to 1,00,00,000)."
    elif editing_fee is not None and amount < editing_fee["paid"]:
        errors["amount"] = f"Amount cannot be lower than the {helpers.inr(editing_fee['paid'])} already paid."
    if not helpers.parse_date(data["due_date"]):
        errors["due_date"] = "Enter a valid due date."
    if len(data["notes"]) > 200:
        errors["notes"] = "Notes are too long (maximum 200 characters)."
    return data, errors


def student_options():
    return db.query_all("SELECT id, student_code, full_name FROM students "
                        "WHERE status <> 'Left' ORDER BY full_name COLLATE NOCASE")


# ------------------------------------------------------------------ list
@bp.route("/")
def list_fees():
    f = {k: clean(request.args.get(k)) for k in ("q", "status", "fee_type", "date_from", "date_to", "student")}
    conditions, params = [], []
    if f["q"]:
        clause, like_params = helpers.search_clause(["fo.student_name", "fo.student_code"], f["q"])
        receipt_clause, receipt_params = helpers.search_clause(["p.receipt_no", "p.transaction_ref"], f["q"])
        conditions.append(f"({clause} OR EXISTS (SELECT 1 FROM payments p WHERE p.fee_id = fo.id AND {receipt_clause}))")
        params += like_params + receipt_params
    if f["status"] in helpers.FEE_STATUSES:
        conditions.append("fo.status = ?")
        params.append(f["status"])
    if f["fee_type"] in helpers.FEE_TYPES:
        conditions.append("fo.fee_type = ?")
        params.append(f["fee_type"])
    if helpers.parse_date(f["date_from"]):
        conditions.append("fo.due_date >= ?")
        params.append(f["date_from"])
    if helpers.parse_date(f["date_to"]):
        conditions.append("fo.due_date <= ?")
        params.append(f["date_to"])
    if helpers.parse_int(f["student"], 1):
        conditions.append("fo.student_id = ?")
        params.append(int(f["student"]))

    base = "SELECT fo.* FROM fee_overview fo" + helpers.where(conditions)
    rows, pager = helpers.paginate(base + " ORDER BY fo.due_date DESC, fo.id DESC", params, helpers.page_number())
    totals = db.query_one(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS amount, COALESCE(SUM(paid),0) AS paid, "
        f"COALESCE(SUM(balance),0) AS balance FROM ({base})", params)
    return render_template("fees.html", fees=rows, pager=pager, totals=totals, filters=f,
                           statuses=helpers.FEE_STATUSES, fee_types=helpers.FEE_TYPES,
                           students=student_options())


# ------------------------------------------------------------------- add
@bp.route("/add", methods=["GET", "POST"])
def add_fee():
    data, errors, pay_data, pay_errors = {}, {}, {}, {}
    if request.method == "POST":
        data, errors = validate_fee(request.form)
        pay_now = request.form.get("pay_now") == "on"
        if pay_now:
            pay_data, pay_errors = validate_payment({**request.form, "amount": request.form.get("amount")})
            pay_errors.pop("amount", None)        # full amount is paid; amount already validated above
        if not errors and not pay_errors:
            database = db.get_db()
            try:
                cursor = database.execute(
                    "INSERT INTO fees (student_id, fee_type, amount, due_date, notes) VALUES (?,?,?,?,?)",
                    (int(data["student_id"]), data["fee_type"], helpers.parse_amount(data["amount"]),
                     data["due_date"], data["notes"] or None))
                fee_id = cursor.lastrowid
                payment_id = None
                if pay_now:
                    payment_id = record_payment(database, fee_id, helpers.parse_amount(data["amount"]),
                                                pay_data["payment_date"], pay_data["method"],
                                                pay_data["transaction_ref"])
                database.commit()
                flash("Fee added" + (" and marked as paid." if pay_now else "."), "success")
                if payment_id:
                    return redirect(url_for("fees.receipt", payment_id=payment_id))
                return redirect(url_for("fees.fee_details", fee_id=fee_id))
            except (ValueError, sqlite3.IntegrityError) as error:
                database.rollback()
                errors["__all__"] = str(error)
        flash("Please correct the highlighted fields.", "danger")
    else:
        data = {"due_date": helpers.today(), "fee_type": "Hostel Rent",
                "student_id": request.args.get("student", "")}
        pay_data = {"payment_date": helpers.today(), "method": "Cash"}
    return render_template("fee_form.html", fee=None, data=data, errors=errors, pay_data=pay_data,
                           pay_errors=pay_errors, students=student_options(),
                           fee_types=helpers.FEE_TYPES, methods=helpers.PAYMENT_METHODS)


# ------------------------------------------------------------------ edit
@bp.route("/<int:fee_id>/edit", methods=["GET", "POST"])
def edit_fee(fee_id):
    fee = db.query_one("SELECT * FROM fee_overview WHERE id = ?", (fee_id,))
    if fee is None:
        abort(404)
    data, errors = dict(fee), {}
    data["amount"] = f"{fee['amount']:.2f}"
    if request.method == "POST":
        data, errors = validate_fee(request.form, editing_fee=fee)
        if not errors:
            database = db.get_db()
            database.execute("UPDATE fees SET fee_type=?, amount=?, due_date=?, notes=? WHERE id=?",
                             (data["fee_type"], helpers.parse_amount(data["amount"]), data["due_date"],
                              data["notes"] or None, fee_id))
            database.commit()
            flash("Fee updated.", "success")
            return redirect(url_for("fees.fee_details", fee_id=fee_id))
        flash("Please correct the highlighted fields.", "danger")
    return render_template("fee_form.html", fee=fee, data=data, errors=errors, pay_data={}, pay_errors={},
                           students=[], fee_types=helpers.FEE_TYPES, methods=helpers.PAYMENT_METHODS)


# --------------------------------------------------------------- details
@bp.route("/<int:fee_id>")
def fee_details(fee_id, pay_data=None, pay_errors=None):
    fee = db.query_one("SELECT * FROM fee_overview WHERE id = ?", (fee_id,))
    if fee is None:
        abort(404)
    payments = db.query_all(
        "SELECT p.*, u.full_name AS received_by_name FROM payments p "
        "LEFT JOIN users u ON u.id = p.received_by WHERE p.fee_id = ? ORDER BY p.payment_date, p.id", (fee_id,))
    defaults = pay_data or {"amount": f"{fee['balance']:.2f}", "payment_date": helpers.today(), "method": "Cash"}
    return render_template("fee_details.html", fee=fee, payments=payments, pay_data=defaults,
                           pay_errors=pay_errors or {}, methods=helpers.PAYMENT_METHODS)


@bp.route("/<int:fee_id>/pay", methods=["POST"])
def pay_fee(fee_id):
    if db.query_one("SELECT 1 FROM fees WHERE id = ?", (fee_id,)) is None:
        abort(404)
    data, errors = validate_payment(request.form)
    if not errors:
        database = db.get_db()
        try:
            payment_id = record_payment(database, fee_id, helpers.parse_amount(data["amount"]),
                                        data["payment_date"], data["method"], data["transaction_ref"])
            database.commit()
            flash("Payment recorded. Receipt generated.", "success")
            return redirect(url_for("fees.receipt", payment_id=payment_id))
        except (ValueError, sqlite3.IntegrityError) as error:
            database.rollback()
            errors["amount"] = str(error)
            flash(str(error), "danger")
    flash("Payment was not recorded. Please check the form.", "danger")
    return fee_details(fee_id, pay_data=data, pay_errors=errors)


@bp.route("/<int:fee_id>/delete", methods=["POST"])
def delete_fee(fee_id):
    fee = db.query_one("SELECT * FROM fee_overview WHERE id = ?", (fee_id,))
    if fee is None:
        abort(404)
    if fee["paid"] > 0:
        flash("This fee already has payments recorded, so it cannot be deleted (financial records are kept).", "danger")
        return redirect(url_for("fees.fee_details", fee_id=fee_id))
    database = db.get_db()
    database.execute("DELETE FROM fees WHERE id = ?", (fee_id,))
    database.commit()
    flash("Fee deleted.", "success")
    return redirect(url_for("fees.list_fees"))


# ------------------------------------------------- payment history / receipt
@bp.route("/payments")
def payment_history():
    f = {k: clean(request.args.get(k)) for k in ("q", "method", "date_from", "date_to")}
    conditions, params = [], []
    if f["q"]:
        clause, like_params = helpers.search_clause(
            ["fo.student_name", "fo.student_code", "p.receipt_no", "p.transaction_ref"], f["q"])
        conditions.append(clause)
        params += like_params
    if f["method"] in helpers.PAYMENT_METHODS:
        conditions.append("p.method = ?")
        params.append(f["method"])
    if helpers.parse_date(f["date_from"]):
        conditions.append("p.payment_date >= ?")
        params.append(f["date_from"])
    if helpers.parse_date(f["date_to"]):
        conditions.append("p.payment_date <= ?")
        params.append(f["date_to"])
    base = ("SELECT p.id, p.amount, p.payment_date, p.method, p.transaction_ref, p.receipt_no, p.fee_id, "
            "fo.student_name, fo.student_code, fo.fee_type FROM payments p "
            "JOIN fee_overview fo ON fo.id = p.fee_id" + helpers.where(conditions))
    rows, pager = helpers.paginate(base + " ORDER BY p.payment_date DESC, p.id DESC", params, helpers.page_number())
    total = db.scalar(f"SELECT COALESCE(SUM(amount),0) FROM ({base})", params)
    return render_template("payments.html", payments=rows, pager=pager, total=total, filters=f,
                           methods=helpers.PAYMENT_METHODS)


@bp.route("/receipt/<int:payment_id>")
def receipt(payment_id):
    payment = db.query_one(
        "SELECT p.*, u.full_name AS received_by_name FROM payments p "
        "LEFT JOIN users u ON u.id = p.received_by WHERE p.id = ?", (payment_id,))
    if payment is None:
        abort(404)
    fee = db.query_one("SELECT * FROM fee_overview WHERE id = ?", (payment["fee_id"],))
    student = db.query_one(
        "SELECT s.*, r.room_no FROM students s LEFT JOIN rooms r ON r.id = s.room_id WHERE s.id = ?",
        (fee["student_id"],))
    settings = {k: db.get_setting(k) for k in ("hostel_name", "hostel_address", "hostel_phone", "hostel_email")}
    return render_template("fee_receipt.html", payment=payment, fee=fee, student=student, settings=settings)
