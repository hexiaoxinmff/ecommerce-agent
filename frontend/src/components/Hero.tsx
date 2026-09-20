import { exampleQuestions } from "../data/demo";
import { IconSpark } from "./Icons";

type HeroProps = {
  query: string;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
};

/** Hero / AI 区域（UI/UX v1.0 第 9.2 节）：高级、干净、有 AI 感，但不做成聊天机器人 */
export function Hero({ query, onQueryChange, onSubmit, disabled }: HeroProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !disabled) {
      onSubmit();
    }
  };

  return (
    <section className="hero fade-in">
      <div className="hero__deco hero__deco--blue" aria-hidden="true" />
      <div className="hero__deco hero__deco--purple" aria-hidden="true" />

      <div className="hero__body">
        <div className="hero__ai-tag">
          <IconSpark className="spark" />
          Text2SQL 智能数据分析
        </div>

        <h2 className="hero__title">用自然语言，直接向数据提问</h2>
        <p className="hero__subtitle">
          让业务问题自动转化为可执行、可验证的数据查询
        </p>

        <div className="hero__search">
          <input
            className="hero__input"
            type="text"
            placeholder="例如：本月销售额是多少？"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label="输入自然语言查询问题"
          />
          <button type="button" className="btn-primary hero__btn" onClick={onSubmit} disabled={disabled}>
            开始分析
          </button>
        </div>

        <div className="hero__examples">
          {exampleQuestions.map((q) => (
            <button
              key={q}
              type="button"
              className="hero__chip"
              onClick={() => onQueryChange(q)}
              disabled={disabled}
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
