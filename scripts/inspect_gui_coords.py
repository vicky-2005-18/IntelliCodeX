import subprocess

java_code = """import java.awt.*;
import javax.swing.*;

public class GetCoords {
    public static void main(String[] args) throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            TodoApp app = new TodoApp();
            app.initGUI();
            Frame[] frames = Frame.getFrames();
            for (Frame f : frames) {
                if (f instanceof JFrame) {
                    JFrame jf = (JFrame) f;
                    Point locOnScreen = jf.getLocationOnScreen();
                    Insets insets = jf.getInsets();
                    System.out.println("FRAME:" + locOnScreen.x + ":" + locOnScreen.y + ":" + jf.getWidth() + ":" + jf.getHeight());
                    System.out.println("INSETS:" + insets.left + ":" + insets.top);
                    printComp(jf.getContentPane(), locOnScreen.x + insets.left, locOnScreen.y + insets.top);
                }
            }
            System.exit(0);
        });
    }

    static void printComp(Component c, int px, int py) {
        int x = px + c.getX();
        int y = py + c.getY();
        if (c instanceof JButton) {
            JButton b = (JButton) c;
            System.out.println("BUTTON:" + b.getText() + ":" + x + ":" + y + ":" + c.getWidth() + ":" + c.getHeight() + " -> Center: " + (x + c.getWidth()/2) + "," + (y + c.getHeight()/2));
        } else if (c instanceof JTextField) {
            System.out.println("TEXTFIELD:" + x + ":" + y + ":" + c.getWidth() + ":" + c.getHeight() + " -> Center: " + (x + c.getWidth()/2) + "," + (y + c.getHeight()/2));
        } else if (c instanceof JList) {
            System.out.println("JLIST:" + x + ":" + y + ":" + c.getWidth() + ":" + c.getHeight() + " -> Center: " + (x + c.getWidth()/2) + "," + (y + c.getHeight()/2));
        }
        if (c instanceof Container) {
            for (Component child : ((Container) c).getComponents()) {
                printComp(child, x, y);
            }
        }
    }
}
"""

with open("scratch/GetCoords.java", "w", encoding="utf-8") as f:
    f.write(java_code)

subprocess.run(["docker", "cp", "scratch/GetCoords.java", "test-gui-container:/tmp/GetCoords.java"], check=True)
compile_cmd = ["docker", "exec", "test-gui-container", "javac", "-cp", "/tmp/build_classes", "-d", "/tmp", "/tmp/GetCoords.java"]
subprocess.run(compile_cmd, check=True)

run_cmd = ["docker", "exec", "-e", "DISPLAY=:99", "test-gui-container", "java", "-cp", "/tmp:/tmp/build_classes", "-Djava.awt.headless=false", "GetCoords"]
res = subprocess.run(run_cmd, capture_output=True, text=True)
print(res.stdout)
