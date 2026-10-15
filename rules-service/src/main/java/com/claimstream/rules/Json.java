package com.claimstream.rules;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Minimal JSON for flat objects (string / number / boolean / null), so the service has zero dependencies. */
final class Json {
    private final String s;
    private int i;

    private Json(String s) { this.s = s; }

    static Map<String, Object> parseObject(String text) {
        Json p = new Json(text.trim());
        Map<String, Object> out = p.object();
        p.ws();
        if (p.i != p.s.length()) throw new IllegalArgumentException("trailing characters at " + p.i);
        return out;
    }

    private Map<String, Object> object() {
        Map<String, Object> m = new LinkedHashMap<>();
        expect('{');
        ws();
        if (peek() == '}') { i++; return m; }
        while (true) {
            ws();
            String k = string();
            ws(); expect(':'); ws();
            m.put(k, value());
            ws();
            char c = s.charAt(i++);
            if (c == '}') return m;
            if (c != ',') throw new IllegalArgumentException("expected , or } at " + (i - 1));
        }
    }

    private Object value() {
        char c = peek();
        if (c == '"') return string();
        if (s.startsWith("true", i)) { i += 4; return Boolean.TRUE; }
        if (s.startsWith("false", i)) { i += 5; return Boolean.FALSE; }
        if (s.startsWith("null", i)) { i += 4; return null; }
        int st = i;
        while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
        if (st == i) throw new IllegalArgumentException("unexpected character at " + i);
        return Double.parseDouble(s.substring(st, i));
    }

    private String string() {
        expect('"');
        StringBuilder b = new StringBuilder();
        while (true) {
            char c = s.charAt(i++);
            if (c == '"') return b.toString();
            if (c == '\\') {
                char e = s.charAt(i++);
                switch (e) {
                    case 'n' -> b.append('\n');
                    case 't' -> b.append('\t');
                    case 'u' -> { b.append((char) Integer.parseInt(s.substring(i, i + 4), 16)); i += 4; }
                    default -> b.append(e);
                }
            } else b.append(c);
        }
    }

    private void ws() { while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++; }
    private char peek() { return s.charAt(i); }
    private void expect(char c) {
        if (s.charAt(i) != c) throw new IllegalArgumentException("expected '" + c + "' at " + i);
        i++;
    }

    static String result(int score, List<String> rules) {
        StringBuilder b = new StringBuilder("{\"score\":").append(score).append(",\"rules\":[");
        for (int k = 0; k < rules.size(); k++) {
            if (k > 0) b.append(',');
            b.append('"').append(rules.get(k)).append('"');
        }
        return b.append("]}").toString();
    }
}
