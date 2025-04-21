import os
from flask import Flask, request, jsonify
import psycopg2
from psycopg2 import sql
from functools import wraps
import datetime
import json

app = Flask(__name__)

# Configure CORS
from flask_cors import CORS
CORS(app)

# API key authentication
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.headers.get('X-API-Key') != os.getenv('API_KEY'):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# Database connection
def get_db_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

# Helper function to convert database rows to dictionaries
def row_to_dict(cursor, row):
    return {col[0]: value for col, value in zip(cursor.description, row)}

# Handle dates and binary data in JSON responses
class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, (bytes, bytearray)):
            return obj.decode('utf-8')
        return json.JSONEncoder.default(self, obj)

app.json_encoder = JSONEncoder

@app.route('/')
def index():
    return jsonify({
        "name": "Discord Ticket Bot API",
        "version": "1.0.0",
        "endpoints": [
            "/stats/guild/<id>",
            "/licenses",
            "/servers"
        ]
    })

@app.route('/stats/guild/<guild_id>')
@require_api_key
def guild_stats(guild_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Get general info
        cur.execute("SELECT server_name, owner_name FROM activated_servers WHERE guild_id = %s", (guild_id,))
        guild_info = cur.fetchone()
        
        if not guild_info:
            return jsonify({"error": "Guild not found"}), 404
        
        guild_data = {
            "id": guild_id,
            "name": guild_info[0],
            "owner": guild_info[1]
        }
        
        # Get ticket stats
        cur.execute("""
            SELECT date, tickets_opened, tickets_closed, avg_resolution_time
            FROM ticket_stats
            WHERE guild_id = %s
            ORDER BY date DESC
            LIMIT 30
        """, (guild_id,))
        ticket_stats = [row_to_dict(cur, row) for row in cur.fetchall()]
        
        # Get feedback stats
        cur.execute("""
            SELECT COUNT(*) as total, AVG(rating) as avg_rating
            FROM feedback
            WHERE guild_id = %s
        """, (guild_id,))
        feedback_overall = row_to_dict(cur, cur.fetchone())
        
        # Get feedback rating distribution
        cur.execute("""
            SELECT rating, COUNT(*) as count
            FROM feedback
            WHERE guild_id = %s
            GROUP BY rating
            ORDER BY rating
        """, (guild_id,))
        feedback_distribution = [row_to_dict(cur, row) for row in cur.fetchall()]
        
        conn.close()
        
        return jsonify({
            "guild": guild_data,
            "tickets": {
                "daily": ticket_stats,
                "total": {
                    "opened": sum(stat["tickets_opened"] for stat in ticket_stats),
                    "closed": sum(stat["tickets_closed"] for stat in ticket_stats),
                    "avg_resolution_time": sum(stat["avg_resolution_time"] * stat["tickets_closed"] 
                                            for stat in ticket_stats if stat["tickets_closed"] > 0) / 
                                            sum(stat["tickets_closed"] for stat in ticket_stats if stat["tickets_closed"] > 0)
                                            if sum(stat["tickets_closed"] for stat in ticket_stats if stat["tickets_closed"] > 0) > 0 else 0
                }
            },
            "feedback": {
                "overall": feedback_overall,
                "distribution": feedback_distribution
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/licenses')
@require_api_key
def list_licenses():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT key_id, key_value, created_at, created_by, used, 
                   used_by, used_at, expires_at 
            FROM license_keys
            ORDER BY created_at DESC
        """)
        
        licenses = [row_to_dict(cur, row) for row in cur.fetchall()]
        conn.close()
        
        return jsonify({"licenses": licenses})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/servers')
@require_api_key
def list_servers():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT a.guild_id, a.server_name, a.owner_id, a.owner_name, 
                   a.activated_at, a.active, l.key_value 
            FROM activated_servers a 
            JOIN license_keys l ON a.key_id = l.key_id 
            ORDER BY a.activated_at DESC
        """)
        
        servers = []
        for row in cur.fetchall():
            server = {
                "guild_id": row[0],
                "server_name": row[1],
                "owner_id": row[2],
                "owner_name": row[3],
                "activated_at": row[4],
                "active": row[5],
                "license_key": row[6]
            }
            
            # Get ticket stats
            cur.execute("""
                SELECT SUM(tickets_opened) as opened, SUM(tickets_closed) as closed
                FROM ticket_stats
                WHERE guild_id = %s
            """, (row[0],))
            stats = cur.fetchone()
            
            server["tickets_opened"] = stats[0] or 0
            server["tickets_closed"] = stats[1] or 0
            
            servers.append(server)
        
        conn.close()
        
        return jsonify({"servers": servers})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
