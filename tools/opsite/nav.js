document.body.insertAdjacentHTML("afterbegin",
  '<header><b>小站</b><a href="/index.html">首页</a><a href="/messages.html">消息</a><a href="/search.html">搜索</a>' +
  '<a href="/news.html">文章</a><a href="/shop.html">商店</a><a href="/profile.html">我的资料</a></header>');

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  return response.json();
}
