// The everyday bench's chat program (tools/everyday.py): one conversation with 小林, a box and 发送. Every change
// of the box and every send is written to the log given first, with the time, so the bench reads what was sent
// and when. A fourth argument slows each change of the box by that many milliseconds (the stop request, E28).
using System; using System.Drawing; using System.IO; using System.Reflection; using System.Threading;
using System.Windows.Forms;
[assembly: AssemblyTitle("聊天")]
[assembly: AssemblyProduct("聊天")]
class Chat : Form {
  static string logPath; static int slow;
  static void Log(string s) {
    double now = (DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds;
    File.AppendAllText(logPath, now.ToString("F2") + " " + s + Environment.NewLine);
  }
  protected override bool ShowWithoutActivation { get { return true; } }
  Chat(int x, int y) {
    Text = "聊天 - 小林"; StartPosition = FormStartPosition.Manual; Location = new Point(x, y);
    ClientSize = new Size(420, 360); Font = new Font("Microsoft YaHei UI", 9);
    var talk = new ListBox { Left = 10, Top = 10, Width = 400, Height = 260, AccessibleName = "消息" };
    talk.Items.Add("小林 昨天 21:40：周末的票我买好了");
    talk.Items.Add("我 昨天 21:42：好呀");
    talk.Items.Add("小林 18:02：今晚七点老地方见？");
    Controls.Add(talk);
    var box = new TextBox { Left = 10, Top = 285, Width = 310, AccessibleName = "输入消息" };
    box.TextChanged += (s, e) => { if (slow > 0) Thread.Sleep(slow); Log("TEXT " + box.Text); };
    Controls.Add(box);
    var send = new Button { Left = 330, Top = 283, Width = 80, Height = 28, Text = "发送" };
    send.Click += (s, e) => { Log("SEND " + box.Text); talk.Items.Add("我 刚刚：" + box.Text); box.Text = ""; };
    Controls.Add(send);
    AcceptButton = send;
    Log("START");
  }
  [STAThread] static void Main(string[] a) {
    logPath = a[0]; slow = a.Length > 3 ? int.Parse(a[3]) : 0;
    Application.EnableVisualStyles(); Application.Run(new Chat(int.Parse(a[1]), int.Parse(a[2])));
  }
}
