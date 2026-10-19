import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;

import ij.IJ;
import ij.ImagePlus;
import ij.gui.Roi;
import ij.plugin.ContrastEnhancer;
import ij.plugin.filter.GaussianBlur;
import ij.process.ImageProcessor;
import java.awt.Rectangle;
import xmipp.ij.commons.XmippImageConverter;
import xmipp.jni.ImageGeneric;
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
 *   filters   filtersFile                         -> ok
 *   templates size  number  templatesFile  particlesFile  -> ok  used
 *   addtemplate size number templatesFile  micrograph  x  y  -> ok  filled
 *   center    size  number  templatesFile  micrograph  x  y  -> ok  x  y  shiftX  shiftY
 *   quit
 * Files: micsFile one micrograph per line; trainFile "micrograph<TAB>posFile";
 * manualFile "x y"; automaticFile and outFile "x y cost enabled";
 * filtersFile "command<TAB>options" (the picker's ImageJ filters);
 * particlesFile "micrograph<TAB>x<TAB>y".
 *
 * Templates and centering do what SupervisedParticlePicker does: particles
 * are boxed from the micrograph as the picker shows it (its filters applied),
 * the templates are their aligned averages (written when all are filled), and
 * a new particle moves to the best shift against the templates' radial
 * average when that shift is under a quarter of the box.
 * Errors answer "error<TAB>message" and keep the session alive.
 */
public class XmippPickerSession {
    private static final String ANSWER = "@@picker ";
    private static PickingClassifier classifier;
    // Desktop picker defaults when the session has no filters.
    private static List<String[]> filters = defaultFilters();
    private static String loadedMicrograph;
    private static ImagePlus loadedImage;
    private static ImageGeneric templates;
    private static ImageGeneric radialTemplates;
    private static int templateIndex;
    private static String templatesKey;

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
                String message = error.getMessage() != null ? error.getMessage() : error.getClass().getSimpleName();
                StackTraceElement[] trace = error.getStackTrace();
                if (error.getMessage() == null && trace.length > 0) message += " at " + trace[0];
                message = message.replace('\n', ' ').replace('\t', ' ');
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
            case "filters": {
                List<String[]> read = new ArrayList<>();
                for (String entry : Files.readAllLines(Paths.get(cmd[1]))) {
                    if (entry.trim().isEmpty()) continue;
                    String[] parts = entry.split("\t", -1);
                    read.add(new String[]{parts[0].trim(), parts.length > 1 ? parts[1].trim() : ""});
                }
                filters = read;
                loadedMicrograph = null;
                loadedImage = null;
                return "ok";
            }
            case "templates": {
                int size = Integer.parseInt(cmd[1]), number = Integer.parseInt(cmd[2]);
                newTemplates(size, number, cmd[3]);
                // As UpdateTemplatesTask: a limited number of particles, fewer when they are big.
                int maximum = size > 256 ? 10 : 50, used = 0;
                for (String entry : Files.readAllLines(Paths.get(cmd[4]))) {
                    if (used >= maximum) break;
                    String[] parts = entry.split("\t");
                    if (parts.length < 3) continue;
                    ImageGeneric particle = box(parts[0], Integer.parseInt(parts[1]), Integer.parseInt(parts[2]), size);
                    if (particle == null) continue;
                    addToTemplates(particle);
                    used++;
                }
                templates.getRadialAvg(radialTemplates);
                saveTemplates(cmd[3], number);
                return "ok\t" + used;
            }
            case "addtemplate": {
                int size = Integer.parseInt(cmd[1]), number = Integer.parseInt(cmd[2]);
                loadTemplates(size, number, cmd[3]);
                ImageGeneric particle = box(cmd[4], Integer.parseInt(cmd[5]), Integer.parseInt(cmd[6]), size);
                if (particle != null) {
                    addToTemplates(particle);
                    templates.getRadialAvg(radialTemplates);
                    saveTemplates(cmd[3], number);
                }
                return "ok\t" + templateIndex;
            }
            case "center": {
                int size = Integer.parseInt(cmd[1]), number = Integer.parseInt(cmd[2]);
                int x = Integer.parseInt(cmd[5]), y = Integer.parseInt(cmd[6]);
                loadTemplates(size, number, cmd[3]);
                ImageGeneric particle = templateIndex > 0 ? box(cmd[4], x, y, size) : null;
                int shiftX = 0, shiftY = 0;
                if (particle != null) {
                    Particle shift = radialTemplates.bestShift(particle);
                    shiftX = shift.getX();
                    shiftY = shift.getY();
                    double distance = Math.sqrt(Math.pow(shiftX, 2) + Math.pow(shiftY, 2)) / size;
                    if (distance < 0.25) {
                        x += shiftX;
                        y += shiftY;
                    }
                }
                // The shift found is also answered (kept or not), for diagnosis.
                return "ok\t" + x + "\t" + y + "\t" + shiftX + "\t" + shiftY;
            }
            default:
                return "error\tunknown command " + cmd[0];
        }
    }

    private static List<String[]> defaultFilters() {
        List<String[]> defaults = new ArrayList<>();
        defaults.add(new String[]{"Gaussian Blur...", "sigma=2"});
        defaults.add(new String[]{"Enhance Contrast", "saturated=0.4"});
        return defaults;
    }

    /** The micrograph as the picker shows it: Micrograph.getImagePlus(filters) and runImageJFilters. */
    private static ImagePlus micrograph(String file) throws Exception {
        if (file.equals(loadedMicrograph) && loadedImage != null) return loadedImage;
        ImagePlus image = null;
        for (String[] filter : filters) {
            if (filter[0].equals("Xmipp Smooth Filter")) {
                ImageGeneric ig = new ImageGeneric(file);
                ig.read(ImageGeneric.FIRST_IMAGE);
                ig.convert2Datatype(ImageGeneric.UChar);
                ImageGeneric smooth = new ImageGeneric(ImageGeneric.UChar);
                smooth.resize(ig.getXDim(), ig.getYDim());
                ig.smooth(smooth);
                image = XmippImageConverter.convertToImagePlus(ig);
                ig.destroy();
                break;
            }
        }
        if (image == null) image = XmippImageConverter.loadImage(file);
        for (String[] filter : filters)
            if (!filter[0].equals("Xmipp Smooth Filter")) applyFilter(image, filter[0], filter[1]);
        loadedMicrograph = file;
        loadedImage = image;
        return image;
    }

    /**
     * One of the picker's ImageJ filters (IJ.run needs a display for some of
     * them, so the usual ones are applied with their ImageJ classes).
     */
    private static void applyFilter(ImagePlus image, String command, String options) {
        String name = command.replace("...", "").trim();
        if (name.equals("Gaussian Blur")) {
            double sigma = optionValue(options, "sigma", 2.0);
            new GaussianBlur().blurGaussian(image.getProcessor(), sigma, sigma, 0.01);
        } else if (name.equals("Enhance Contrast")) {
            // Without "normalize" it changes the display range, not the pixels the boxes take.
            if (options.contains("normalize"))
                new ContrastEnhancer().stretchHistogram(image.getProcessor(), optionValue(options, "saturated", 0.35));
        } else if (!name.equals("Invert LUT")) {  // Display only.
            try {
                IJ.run(image, command, options);
            } catch (Throwable error) {
                System.err.println("Filter " + command + " skipped: " + error);
            }
        }
    }

    private static double optionValue(String options, String key, double fallback) {
        for (String part : options.trim().split("\\s+")) {
            String[] pair = part.split("=", 2);
            if (pair.length == 2 && pair[0].equals(key)) {
                try {
                    return Double.parseDouble(pair[1]);
                } catch (NumberFormatException ignored) {
                    return fallback;
                }
            }
        }
        return fallback;
    }

    /** The particle's box, as ManualParticle.loadImagePlus; null when it does not fit (Micrograph.fits). */
    private static ImageGeneric box(String file, int x, int y, int size) throws Exception {
        ImagePlus image = micrograph(file);
        int radius = size / 2;
        if (x < 0 || y < 0 || x - radius < 0 || x + radius > image.getWidth()
                || y - radius < 0 || y + radius > image.getHeight())
            return null;
        Roi roi = image.getRoi();
        image.setRoi(new Rectangle(x - radius, y - radius, size, size));
        ImageProcessor processor = image.getProcessor().crop();
        image.setRoi(roi);
        return XmippImageConverter.convertToImageGeneric(new ImagePlus("", processor));
    }

    private static void newTemplates(int size, int number, String file) throws Exception {
        templates = new ImageGeneric(ImageGeneric.Float);
        templates.resize(size, size, 1, number);
        radialTemplates = new ImageGeneric(ImageGeneric.Float);
        radialTemplates.resize(size, size, 1, number);
        templateIndex = 0;
        templatesKey = size + ":" + number + ":" + file;
    }

    /** As the SupervisedParticlePicker constructor: the stored templates, or empty ones. */
    private static void loadTemplates(int size, int number, String file) throws Exception {
        String key = size + ":" + number + ":" + file;
        if (key.equals(templatesKey) && templates != null) return;
        newTemplates(size, number, file);
        if (Files.exists(Paths.get(file))) {
            ImageGeneric stored = new ImageGeneric(file);
            if (stored.getXDim() == size && stored.getYDim() == size && stored.getNDim() == number) {
                stored.read(file, false);
                templates = stored;
                templateIndex = (templates.getStatistics()[2] == 0) ? 0 : number;
            }
        }
        templates.getRadialAvg(radialTemplates);
    }

    /** As addParticleToTemplates: fill the templates first, then align and average into them. */
    private static void addToTemplates(ImageGeneric particle) throws Exception {
        long number = templates.getNDim();
        if (templateIndex < number) {
            float[] matrix = particle.getArrayFloat(ImageGeneric.FIRST_IMAGE, ImageGeneric.FIRST_SLICE);
            templates.setArrayFloat(matrix, ImageGeneric.FIRST_IMAGE + templateIndex, ImageGeneric.FIRST_SLICE);
            templateIndex++;
        } else {
            double[] align = templates.alignImage(particle);
            // ManualParticle.getTemplateIndex/Rotation/Tilt/Psi read these from the alignment.
            templates.applyAlignment(particle, (int) align[0], align[1], align[2], align[3]);
        }
    }

    /** As saveTemplates: only complete templates are written (then a reload knows they are filled). */
    private static void saveTemplates(String file, int number) throws Exception {
        if (templateIndex == number) templates.write(file);
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
