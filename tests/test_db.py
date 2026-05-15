import pymysql

# 替换为你的实际密码
password = "Dzm@ming&662"

try:
    # 连接数据库
    connection = pymysql.connect(
        host='115.29.213.22',
        port=3306,
        user='root',
        password=password,
        database='quantiadb',  # 替换为你的数据库名，如果不确定可以先不填或填 mysql
        charset='utf8mb4'
    )
    print("✅ 连接成功！")
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()
        print(f"数据库版本: {version}")
        
except Exception as e:
    print(f"❌ 连接失败: {e}")
finally:
    if 'connection' in locals():
        connection.close()
