import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import dashboard_renderer as renderer


class MathRenderingTests(unittest.TestCase):
    def render(self, tex):
        return BeautifulSoup(renderer.render_equations([
            dict(label='계층제어 운동방정식', latex=tex, explanation='수식 설명'),
        ]), 'html.parser')

    def test_reported_equation_has_real_subscripts_and_superscripts(self):
        tex = r'[-M\; I]x_d=b+g+J^Tf_t^{des}'
        page = self.render(tex)
        self.assertEqual(page.math['display'], 'block')
        self.assertIsNotNone(page.find('msub'))
        self.assertIsNotNone(page.find('msup'))
        self.assertIsNotNone(page.find('msubsup'))
        self.assertEqual(page.annotation.text, tex)
        self.assertIsNone(page.code)
        self.assertEqual(page.p.text, '수식 설명')

    def test_fractions_and_piecewise_equations_compile(self):
        page = self.render(r'\begin{cases}\frac{a}{b},&x>0\\0,&x\leq0\end{cases}')
        self.assertIsNotNone(page.find('mfrac'))
        self.assertIsNotNone(page.find('mtable'))

    def test_invalid_tex_fails_instead_of_publishing_raw_source(self):
        with self.assertRaisesRegex(ValueError, 'Equation rendering failed'):
            self.render(r'\frac{a}')

    def test_empty_equations_and_escaped_content(self):
        self.assertEqual(renderer.render_equations([]), '')
        page = self.render(r'\text{<script>alert(1)</script>}')
        self.assertIsNone(page.script)


if __name__ == '__main__':
    unittest.main()
