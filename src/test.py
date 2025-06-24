import asyncio
import asyncpg

async def test_connection():
    try:
        print("Тестируем подключение к базе...")
        
        # Попробуйте разные варианты строки подключения
        connection_strings = [
            "postgresql://bot_reader:reader123@172.20.10.13:5432/сбербот",
            "postgresql://bot_reader:reader123@172.20.10.13:5432/сбер_bot", 
            "postgresql://bot_reader:reader123@172.20.10.13:5432/sber_bot",
        ]
        
        for conn_str in connection_strings:
            try:
                print(f"Пробуем: {conn_str}")
                conn = await asyncpg.connect(conn_str)
                result = await conn.fetchval("SELECT 1")
                await conn.close()
                print(f"✅ УСПЕХ! Рабочая строка: {conn_str}")
                return conn_str
            except Exception as e:
                print(f"❌ Ошибка: {e}")
        
        print("❌ Ни одна строка подключения не работает")
        return None
        
    except Exception as e:
        print(f"Общая ошибка: {e}")

asyncio.run(test_connection())