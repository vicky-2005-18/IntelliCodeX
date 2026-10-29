import java.awt.*;
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
