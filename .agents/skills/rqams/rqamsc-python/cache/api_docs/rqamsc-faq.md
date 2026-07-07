## 常见问题

### 线程安全和在子进程中使用 rqamsc

rqamsc 是线程安全的，在当前进程的任何线程中调用 rqamsc 的 api 都是安全的。

在子进程中的 rqamsc：假设您正在当前进程中使用 rqamsc，接着 fork 创建了一个子进程，那么父子进程的 rqamsc 是互相隔离的。
如何理解互相隔离呢：例如您在父进程中切换工作空间，该操作不会影响到子进程 rqamsc 所处的工作空间。可以简单认为子进程里的
rqamsc 是一个全新的 rqamsc，和父进程里的完全没关系。

---

### 私有 rqams 平台

默认情况下您访问的是米筐官方 RQAMS 平台，若您申请了一套私有 RQAMS 平台，也是可以使用 rqamsc 访问的, 这只需要在 uri 参数中指定私有
RQAMS 平台的地址（即在浏览器中可访问 AMS 的网址，保留至.com 后缀 或 有端口号需保留至端口号）。 (
如有私有化部署需求，可以通过米筐官方网站联系我们。)

```python
import rqamsc

rqamsc.init(username='demo@example.com', password='****', uri='your_ams_site.your_ams_domain.com')
```

---
