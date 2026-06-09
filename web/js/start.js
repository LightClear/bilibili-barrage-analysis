document.addEventListener('DOMContentLoaded', () => {
  const loginBtn = document.getElementById('loginBtn');
  loginBtn.href = './login.html';
  fetch('/api/account/session', { cache: 'no-store' })
    .then((resp) => resp.json())
    .then((data) => {
      if (!data.ok || !data.logged_in) return;
      loginBtn.innerHTML = `${loginBtn.querySelector('svg').outerHTML}个人页面<span class="login-en">ACCOUNT</span>`;
    })
    .catch(() => {
      // 静态打开 start.html 时保持默认登入入口。
    });
});
