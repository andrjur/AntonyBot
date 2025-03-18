 """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL DEFAULT '◊≈¡”–¿ÿ ¿',
                birthday TEXT,
                registration_date TEXT,
                referral_count INTEGER DEFAULT 0,
                penalty_task TEXT,
                preliminary_material_index INTEGER DEFAULT 0,
                tariff TEXT,
                continuous_flow BOOLEAN DEFAULT 0,
                next_lesson_time DATETIME,
                active_course_id TEXT,
                user_code TEXT,
                last_bonus_date TEXT,
                trust_credit INTEGER DEFAULT 0,
                support_requests INTEGER DEFAULT 0,
                morning_time TEXT,   
                evening_time TEXT    
            );

            CREATE TABLE IF NOT EXISTS homeworks (
                hw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                course_id TEXT,  
                lesson INTEGER,
                file_id TEXT,
                file_type TEXT,
                message_id INTEGER,
                status TEXT DEFAULT 'pending',
                feedback TEXT,
                timestamp TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                lesson_sent_time DATETIME,
                first_submission_time DATETIME,
                submission_time DATETIME,
                approval_time DATETIME,
                final_approval_time DATETIME,
                admin_comment TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS user_tokens (
                user_id INTEGER PRIMARY KEY,
                tokens INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT, 
                amount INTEGER,
                reason TEXT, 
                timestamp TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS lootboxes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                box_type TEXT, 
                reward TEXT, 
                probability REAL 
            );

            CREATE TABLE IF NOT EXISTS admins (
                admin_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS admin_codes (
                code_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                code TEXT,
                created_at TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                used BOOLEAN DEFAULT FALSE,
                FOREIGN KEY(admin_id) REFERENCES admins(admin_id)
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                morning_notification TIME,
                evening_notification TIME,
                show_example_homework BOOLEAN DEFAULT 1,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                price INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_courses (
                user_id INTEGER,
                course_id TEXT,
                course_type TEXT CHECK(course_type IN ('main', 'auxiliary')),
                progress INTEGER DEFAULT 0,
                purchase_date TEXT DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                tariff TEXT,
                PRIMARY KEY (user_id, course_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            """
