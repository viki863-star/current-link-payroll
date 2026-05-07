#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app

def debug_html():
    app = create_app()
    
    with app.test_client() as client:
        # Set up session for admin access
        with client.session_transaction() as session:
            session['role'] = 'admin'
            session['user_id'] = 'test_admin'
        
        # Access the Online Suppliers page
        response = client.get('/suppliers')
        
        if response.status_code != 200:
            print(f"Error: Status code {response.status_code}")
            return
        
        html = response.get_data(as_text=True)
        
        # Save to file for inspection
        with open('debug_statistics_output.html', 'w', encoding='utf-8') as f:
            f.write(html)
        
        print("HTML saved to debug_statistics_output.html")
        
        # Extract just the statistics section
        import re
        
        # Find admin-mini-stats section
        mini_stats_match = re.search(r'<div class="admin-mini-stats">(.*?)</div>', html, re.DOTALL)
        if mini_stats_match:
            print("\n=== Top Toolbar Statistics ===")
            print(mini_stats_match.group(0)[:500])
            
            # Find all <strong> elements in this section
            strong_matches = re.findall(r'<strong>([^<]+)</strong>', mini_stats_match.group(0))
            print(f"\nStrong elements in toolbar: {strong_matches}")
            
            # Find all <small> elements
            small_matches = re.findall(r'<small>([^<]+)</small>', mini_stats_match.group(0))
            print(f"Small labels in toolbar: {small_matches}")
        
        # Find quick-stats-grid section
        quick_stats_match = re.search(r'<div class="quick-stats-grid online-stats-grid">(.*?)</div>', html, re.DOTALL)
        if quick_stats_match:
            print("\n=== Side Panel Statistics ===")
            print(quick_stats_match.group(0)[:500])
            
            # Find stat-value elements
            stat_value_matches = re.findall(r'<span class="stat-value">([^<]+)</span>', quick_stats_match.group(0))
            print(f"\nStat values in side panel: {stat_value_matches}")
            
            # Find stat-label elements
            stat_label_matches = re.findall(r'<span class="stat-label">([^<]+)</span>', quick_stats_match.group(0))
            print(f"Stat labels in side panel: {stat_label_matches}")
        
        # Check for specific text
        check_texts = [
            "Pending Inquiries",
            "Pending Quotations", 
            "Portal Users",
            "Active Suppliers",
            "Fleet Units",
            "Total Due"
        ]
        
        print("\n=== Text Search Results ===")
        for text in check_texts:
            if text in html:
                print(f"[FOUND] '{text}'")
            else:
                print(f"[NOT FOUND] '{text}'")

if __name__ == "__main__":
    debug_html()