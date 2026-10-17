// SPDX-License-Identifier: GPL-3.0-or-later
package io.github.rickamaral94.recompandroid

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.zip.ZipInputStream

class DiagnosticBundleTest {
    private fun entries(zip: ByteArray): List<Pair<String, ByteArray>> {
        val out = mutableListOf<Pair<String, ByteArray>>()
        ZipInputStream(ByteArrayInputStream(zip)).use { z ->
            while (true) {
                val e = z.nextEntry ?: break
                out += e.name to z.readBytes()
            }
        }
        return out
    }

    @Test
    fun reportComesFirstAndLogsAreUnderLogsDir() {
        val report = """{"schema":"recomp_android.diagnostic-report"}""".toByteArray()
        val buf = ByteArrayOutputStream()
        DiagnosticBundle.write(buf, report, mapOf("session.log" to "b".toByteArray(), "logcat.txt" to "a".toByteArray()))
        val e = entries(buf.toByteArray())
        assertEquals(listOf("report.json", "logs/logcat.txt", "logs/session.log"), e.map { it.first })
        assertArrayEquals(report, e[0].second)
    }

    @Test
    fun utf8ReportIsByteExact() {
        val report = """{"model":"ação 🎮"}""".toByteArray(Charsets.UTF_8)
        val buf = ByteArrayOutputStream()
        DiagnosticBundle.write(buf, report, emptyMap())
        assertArrayEquals(report, entries(buf.toByteArray()).single().second)
    }

    @Test
    fun longLogsKeepTheirTail() {
        val big = ByteArray(DiagnosticBundle.MAX_LOG_BYTES + 10) { (it % 251).toByte() }
        val t = DiagnosticBundle.tail(big)
        val text = String(t, 0, 64, Charsets.US_ASCII)
        assertTrue(text, text.startsWith("[... truncated 10 bytes ...]"))
        assertArrayEquals(big.copyOfRange(10, big.size), t.copyOfRange(t.size - DiagnosticBundle.MAX_LOG_BYTES, t.size))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsPathTraversal() {
        DiagnosticBundle.write(ByteArrayOutputStream(), ByteArray(0), mapOf("../x" to ByteArray(0)))
    }

    @Test
    fun fileNameIsStable() {
        assertEquals("recomp_android-diag-20261017-120000.zip", DiagnosticBundle.fileName("20261017-120000"))
    }
}
