import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import xmipp.jni.MDLabel;
import xmipp.jni.MDRow;
import xmipp.jni.Particle;
import xmipp.jni.PickingClassifier;

/**
 * Headless session around Xmipp's supervised picking classifier (the one the
 * desktop picker uses). The classifier stays in memory for the whole session,
 * as correct() needs the candidates of the previous autopick.
 *
 * One tab-separated command per line on stdin, one answer per line on stdout:
 *   create    size  modelRoot  micsFile           -> ok
 *   train     trainFile  x  y  width  height      -> ok
 *   autopick  micrograph  percent  outFile        -> ok  count
 *   correct   manualFile  automaticFile           -> ok
 *   threshold                                     -> ok  n
 *   quit
 * Files: micsFile one micrograph per line; trainFile "micrograph<TAB>posFile";
 * manualFile "x y"; automaticFile and outFile "x y cost enabled".
 * Errors answer "error<TAB>message" and keep the session alive.
 */
public class XmippPickerSession {
    private static final String ANSWER = "@@picker ";
    private static PickingClassifier classifier;

    public static void main(String[] args) throws Exception {
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
        PrintWriter out = new PrintWriter(System.out, true);
        String line;
        while ((line = in.readLine()) != null) {
            String[] cmd = line.split("\t");
            if (cmd.length == 0 || cmd[0].isEmpty()) continue;
            if (cmd[0].equals("quit")) break;
            try {
                out.println(ANSWER + run(cmd));
            } catch (Throwable error) {
                String message = String.valueOf(error.getMessage()).replace('\n', ' ').replace('\t', ' ');
                out.println(ANSWER + "error\t" + message);
            }
            out.flush();
        }
        if (classifier != null) classifier.destroy();
    }

    private static String run(String[] cmd) throws Exception {
        switch (cmd[0]) {
            case "create": {
                List<MDRow> mics = new ArrayList<>();
                for (String mic : Files.readAllLines(Paths.get(cmd[3]))) {
                    if (mic.isEmpty()) continue;
                    MDRow row = new MDRow();
                    row.setValueString(MDLabel.MDL_MICROGRAPH, mic);
                    mics.add(row);
                }
                if (classifier != null) classifier.destroy();
                classifier = new PickingClassifier(Integer.parseInt(cmd[1]), cmd[2], mics.toArray(new MDRow[0]));
                return "ok";
            }
            case "train": {
                List<MDRow> rows = new ArrayList<>();
                for (String entry : Files.readAllLines(Paths.get(cmd[1]))) {
                    if (entry.isEmpty()) continue;
                    String[] parts = entry.split("\t");
                    MDRow row = new MDRow();
                    row.setValueString(MDLabel.MDL_MICROGRAPH, parts[0]);
                    row.setValueString(MDLabel.MDL_MICROGRAPH_PARTICLES, parts[1]);
                    rows.add(row);
                }
                requireClassifier().train(rows.toArray(new MDRow[0]), Integer.parseInt(cmd[2]),
                        Integer.parseInt(cmd[3]), Integer.parseInt(cmd[4]), Integer.parseInt(cmd[5]));
                return "ok";
            }
            case "autopick": {
                Particle[] particles = requireClassifier().autopick(cmd[1], Integer.parseInt(cmd[2]));
                StringBuilder text = new StringBuilder();
                for (Particle p : particles)
                    text.append(p.getX()).append(' ').append(p.getY()).append(' ').append(p.getCost()).append(" 1\n");
                Files.write(Paths.get(cmd[3]), text.toString().getBytes());
                return "ok\t" + particles.length;
            }
            case "correct": {
                requireClassifier().correct(readRows(cmd[1], false), readRows(cmd[2], true));
                return "ok";
            }
            case "threshold":
                return "ok\t" + requireClassifier().getParticlesThreshold();
            default:
                return "error\tunknown command " + cmd[0];
        }
    }

    private static PickingClassifier requireClassifier() {
        if (classifier == null) throw new IllegalStateException("create the classifier first");
        return classifier;
    }

    private static MDRow[] readRows(String file, boolean automatic) throws Exception {
        List<MDRow> rows = new ArrayList<>();
        for (String entry : Files.readAllLines(Paths.get(file))) {
            String[] parts = entry.trim().split("\\s+");
            if (parts.length < 2) continue;
            MDRow row = new MDRow();
            row.setValueInt(MDLabel.MDL_XCOOR, Integer.parseInt(parts[0]));
            row.setValueInt(MDLabel.MDL_YCOOR, Integer.parseInt(parts[1]));
            if (automatic) {
                row.setValueDouble(MDLabel.MDL_COST, Double.parseDouble(parts[2]));
                row.setValueInt(MDLabel.MDL_ENABLED, Integer.parseInt(parts[3]));
            }
            rows.add(row);
        }
        return rows.toArray(new MDRow[0]);
    }
}
