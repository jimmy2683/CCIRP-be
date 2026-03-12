from pymongo.errors import ConnectionFailure
from src.database import get_database, connect_to_mongo
import asyncio
from src.templates.schemas import TemplateCreate
from src.templates.service import TemplateService

async def check_db_connection():
    try:
        await connect_to_mongo()
        db = get_database()
        await db.command("ping")
        print("MongoDB connection is healthy!")
        
        # Test creating a template
        test_template = TemplateCreate(
            name="Welcome Email",
            category="Onboarding",
            channel="Email",
            subject="Welcome to CCIRP!",
            body_html="<h1>Hi {{name}}</h1><p>Welcome to our platform!</p>"
        )
        print("Inserting template...")
        created = await TemplateService.create_template(test_template)
        print(f"Created template: {created['_id']}")
        
        print("Fetching templates...")
        templates = await TemplateService.get_templates()
        print(f"Found {len(templates)} templates:")
        for t in templates:
            print(f"- {t['name']} (v{t['version']})")
    
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    asyncio.run(check_db_connection())
