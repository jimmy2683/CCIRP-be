from src.database import get_database, connect_to_mongo
import asyncio
from src.recipients.schemas import RecipientCreate, RecipientUpdate
from src.recipients.service import create_recipient, get_recipients, get_recipient, update_recipient, delete_recipient

async def test_recipients():
    try:
        await connect_to_mongo()
        db = get_database()
        await db.command("ping")
        print("MongoDB connection is healthy!")
        
        test_user_id = "test_run_user_999"
        
        # 1. Test create
        print("--- Testing Create Recipient ---")
        test_recipient = RecipientCreate(
            email="testrecipient@example.com",
            first_name="John",
            last_name="Doe",
            attributes={"company": "Acme Corp"},
            tags=["vip", "newsletter"]
        )
        created = await create_recipient(test_user_id, test_recipient)
        print(f"Created recipient: {created.id}")
        
        # 2. Test Get All
        print("--- Testing Get Recipients ---")
        recipients = await get_recipients(test_user_id)
        print(f"Found {len(recipients)} recipients for user {test_user_id}")
        
        # 3. Test Get One
        print("--- Testing Get Recipient ---")
        fetched = await get_recipient(test_user_id, str(created.id))
        print(f"Fetched recipient: {fetched.first_name} {fetched.last_name}")
        
        # 4. Test Update
        print("--- Testing Update Recipient ---")
        update_data = RecipientUpdate(first_name="Johnny", status="unsubscribed")
        updated = await update_recipient(test_user_id, str(created.id), update_data)
        print(f"Updated recipient status to: {updated.status}, Name: {updated.first_name}")
        
        # 5. Test Delete
        print("--- Testing Delete Recipient ---")
        await delete_recipient(test_user_id, str(created.id))
        print("Deleted successfully!")
        
        # Verify deletion
        try:
            await get_recipient(test_user_id, str(created.id))
        except Exception as e:
            print(f"Verified deletion: caught expected error ({e})")

    except Exception as e:
        print(f"Test failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(test_recipients())
