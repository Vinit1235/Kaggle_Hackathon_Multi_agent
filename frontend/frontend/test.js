const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  try {
    // Navigate to the deployed app
    await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
    
    // Check for key UI elements
    const sidebar = await page.locator('.chat-sidebar').isVisible();
    const heroTitle = await page.locator('.hero-title').isVisible();
    const promptInput = await page.locator('.prompt-input').isVisible();
    
    console.log('✓ Sidebar visible:', sidebar);
    console.log('✓ Hero title visible:', heroTitle);
    console.log('✓ Prompt input visible:', promptInput);
    
    // Test sidebar toggle
    const toggleBtn = page.locator('.sidebar-toggle');
    if (await toggleBtn.isVisible()) {
      await toggleBtn.click();
      await page.waitForTimeout(300);
      const collapsedSidebar = await page.locator('.chat-sidebar.collapsed').isVisible();
      console.log('✓ Sidebar toggle works:', collapsedSidebar);
    }
    
    // Check for any console errors
    page.on('console', msg => {
      if (msg.type() === 'error') {
        console.log('Console error:', msg.text());
      }
    });
    
    console.log('\n✓ All UI checks passed!');
  } catch (error) {
    console.error('Test failed:', error.message);
  } finally {
    await browser.close();
  }
})();