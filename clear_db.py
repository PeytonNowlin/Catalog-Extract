#!/usr/bin/env python3
"""
Database Clear Script for Development
Clears database tables and optionally uploaded/output files
"""
import os
import sys
import shutil
from pathlib import Path
from sqlalchemy import text

from src.database import SessionLocal, Base, engine, reset_db


def clear_database_data():
    """Clear all data from database tables but keep schema."""
    print("🗑️  Clearing database data...")
    
    db = SessionLocal()
    try:
        # Delete in order to respect foreign key constraints
        tables = ['consolidated_items', 'extracted_items', 'extraction_passes', 'documents']
        
        for table in tables:
            result = db.execute(text(f"DELETE FROM {table}"))
            count = result.rowcount
            print(f"   ✓ Cleared {count} rows from {table}")
        
        db.commit()
        print("✅ Database data cleared successfully!\n")
        return True
        
    except Exception as e:
        print(f"❌ Error clearing database: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def reset_database_schema():
    """Drop and recreate all database tables."""
    print("🔄 Resetting database schema...")
    
    try:
        reset_db()
        print("✅ Database schema reset successfully!\n")
        return True
    except Exception as e:
        print(f"❌ Error resetting database: {e}")
        return False


def clear_uploads():
    """Clear uploaded PDF files."""
    upload_dir = Path("uploads")
    
    if not upload_dir.exists():
        print("ℹ️  No uploads directory found\n")
        return True
    
    print("🗑️  Clearing uploaded files...")
    
    try:
        file_count = 0
        for file_path in upload_dir.glob("*.pdf"):
            file_path.unlink()
            file_count += 1
        
        print(f"   ✓ Deleted {file_count} uploaded files")
        print("✅ Uploads cleared successfully!\n")
        return True
        
    except Exception as e:
        print(f"❌ Error clearing uploads: {e}")
        return False


def clear_outputs():
    """Clear output directory."""
    output_dir = Path("outputs")
    
    if not output_dir.exists():
        print("ℹ️  No outputs directory found\n")
        return True
    
    print("🗑️  Clearing output files...")
    
    try:
        dir_count = 0
        file_count = 0
        
        for item in output_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
                dir_count += 1
            elif item.is_file():
                item.unlink()
                file_count += 1
        
        print(f"   ✓ Deleted {dir_count} directories and {file_count} files")
        print("✅ Outputs cleared successfully!\n")
        return True
        
    except Exception as e:
        print(f"❌ Error clearing outputs: {e}")
        return False


def print_menu():
    """Print menu options."""
    print("\n" + "=" * 60)
    print("Database Clear Script - Development Tool")
    print("=" * 60)
    print()
    print("Choose what to clear:")
    print()
    print("  1. Clear database data only (keep schema)")
    print("  2. Reset database schema (drop & recreate tables)")
    print("  3. Clear uploaded files")
    print("  4. Clear output files")
    print("  5. Clear everything (database + files)")
    print("  6. Clear database data + files")
    print()
    print("  0. Exit")
    print()


def main():
    """Main function."""
    
    # Check if running with arguments
    if len(sys.argv) > 1:
        option = sys.argv[1]
        
        if option == "--data":
            clear_database_data()
        elif option == "--reset":
            reset_database_schema()
        elif option == "--uploads":
            clear_uploads()
        elif option == "--outputs":
            clear_outputs()
        elif option == "--all":
            clear_database_data()
            clear_uploads()
            clear_outputs()
        elif option == "--help":
            print("Usage: python clear_db.py [option]")
            print()
            print("Options:")
            print("  --data      Clear database data only")
            print("  --reset     Reset database schema")
            print("  --uploads   Clear uploaded files")
            print("  --outputs   Clear output files")
            print("  --all       Clear everything")
            print("  --help      Show this help")
            print()
            print("Or run without arguments for interactive menu")
        else:
            print(f"Unknown option: {option}")
            print("Run with --help for usage information")
        
        return
    
    # Interactive menu
    while True:
        print_menu()
        choice = input("Enter your choice (0-6): ").strip()
        print()
        
        if choice == "0":
            print("👋 Exiting...")
            break
            
        elif choice == "1":
            clear_database_data()
            input("Press Enter to continue...")
            
        elif choice == "2":
            confirm = input("⚠️  This will DROP all tables! Are you sure? (yes/no): ")
            if confirm.lower() == "yes":
                reset_database_schema()
            else:
                print("❌ Cancelled\n")
            input("Press Enter to continue...")
            
        elif choice == "3":
            clear_uploads()
            input("Press Enter to continue...")
            
        elif choice == "4":
            clear_outputs()
            input("Press Enter to continue...")
            
        elif choice == "5":
            confirm = input("⚠️  This will clear EVERYTHING! Are you sure? (yes/no): ")
            if confirm.lower() == "yes":
                reset_database_schema()
                clear_uploads()
                clear_outputs()
            else:
                print("❌ Cancelled\n")
            input("Press Enter to continue...")
            
        elif choice == "6":
            clear_database_data()
            clear_uploads()
            clear_outputs()
            input("Press Enter to continue...")
            
        else:
            print("❌ Invalid choice. Please enter 0-6\n")
            input("Press Enter to continue...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)

