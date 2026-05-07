#!/usr/bin/env python3
"""Test cash supplier routes"""

import sys
import os
sys.path.insert(0, '.')

from app import create_app

def test_routes():
    app = create_app()
    print('Testing cash supplier routes...')
    
    with app.test_client() as client:
        # Test 1: cash_work_entry route
        print('1. Checking cash_work_entry route...')
        response = client.get('/suppliers/TEST-001/work-entry', follow_redirects=True)
        print(f'   Status: {response.status_code}')
        
        # Test 2: cash_advance route
        print('2. Checking cash_advance route...')
        response = client.get('/suppliers/TEST-001/advance', follow_redirects=True)
        print(f'   Status: {response.status_code}')
        
        # Test 3: cash_payment route
        print('3. Checking cash_payment route...')
        response = client.get('/suppliers/TEST-001/payment', follow_redirects=True)
        print(f'   Status: {response.status_code}')
        
        print('\nRoutes test completed.')
        print('Note: Routes should return 302 (redirect) or 200 if logged in.')

if __name__ == '__main__':
    test_routes()