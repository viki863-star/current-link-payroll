import sys
sys.path.insert(0,'.')
from app import create_app
app = create_app()
with app.test_client() as c:
    with c.session_transaction() as sess:
        sess['role'] = 'admin'
    resp = c.get('/hr/salary-dashboard')
    html = resp.data.decode('utf-8')
    print('Has createRoot:', 'createRoot' in html)
    print('Has useState:', 'useState' in html)
    print('Has SummaryCards:', 'SummaryCards' in html)
    print('Has root div:', '<div id="salary-dashboard-root"' in html)
    print('Script tag count:', html.count('<script'))
    print('Total length:', len(html))
    print('---LAST 500---')
    print(html[-500:])
